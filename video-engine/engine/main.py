"""Engine entrypoint: ``python -m engine.main``.

Boot sequence:
  1. detect hardware, connect MQTT, publish retained hardware report (§1.3)
  2. fetch cameras from the backend (`GET /internal/cameras`, X-Internal-Token)
     with retry/backoff until the backend is up
  3. spawn one CameraWorker per enabled camera
  4. subscribe `horus/engine/command` for reload/restart commands (§1.4)
  5. run the retention loop; exit cleanly on SIGTERM/SIGINT
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
from typing import Any

import httpx

from engine.config import Settings, load_settings
from engine.hardware import HardwareReport, detect_hardware, opencv_capture_options
from engine.mqtt import MqttClient
from engine.objects import ObjectDetector
from engine.retention import RetentionLoop
from engine.worker import CameraWorker

log = logging.getLogger("engine.main")

COMMAND_TOPIC = "horus/engine/command"
HARDWARE_TOPIC = "horus/engine/hardware"


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def fetch_cameras(settings: Settings, stop: threading.Event) -> list[dict[str, Any]]:
    """GET /internal/cameras with retry+backoff until the backend answers."""
    url = f"{settings.backend_url}/internal/cameras"
    headers = {"X-Internal-Token": settings.internal_api_token}
    backoff = 2.0
    while not stop.is_set():
        try:
            response = httpx.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            cameras = response.json()
            if not isinstance(cameras, list):
                raise ValueError(f"unexpected payload type: {type(cameras).__name__}")
            log.info("Fetched %d cameras from backend", len(cameras))
            return cameras
        except Exception as exc:  # noqa: BLE001 - backend may not be up yet
            log.warning("Backend not ready (%s); retrying in %.0fs", exc, backoff)
            if stop.wait(backoff):
                break
            backoff = min(backoff * 2, 30.0)
    return []


class Engine:
    """Owns workers, MQTT, retention; serializes reload/restart commands."""

    def __init__(self, settings: Settings, hardware: HardwareReport | None = None) -> None:
        self.settings = settings
        self.stop_event = threading.Event()
        self.hardware: HardwareReport = hardware or detect_hardware()
        self.mqtt = MqttClient(settings.mqtt_host, settings.mqtt_port)
        self.object_detector = ObjectDetector(
            settings.model_path, self.hardware.selected_inference)
        self._workers: dict[int, CameraWorker] = {}
        self._cameras: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.retention = RetentionLoop(
            settings.media_root, settings.max_disk_usage_pct,
            cameras_provider=self.current_cameras,
            interval_s=settings.retention_interval_s,
        )

    # -- camera/worker management -------------------------------------------------

    def current_cameras(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._cameras)

    def apply_cameras(self, cameras: list[dict[str, Any]]) -> None:
        """Diff the fetched list against running workers; start/stop/restart."""
        enabled = {int(c["id"]): c for c in cameras if c.get("enabled", True)}
        with self._lock:
            self._cameras = cameras
            current = dict(self._workers)

        for cid, worker in current.items():
            new_cfg = enabled.get(cid)
            if new_cfg is None:
                log.info("camera %s: removed/disabled; stopping worker", cid)
                self._stop_worker(cid)
            elif new_cfg != worker.camera:
                log.info("camera %s: config changed; restarting worker", cid)
                self._stop_worker(cid)
                self._start_worker(new_cfg)

        for cid, cfg in enabled.items():
            with self._lock:
                running = cid in self._workers
            if not running:
                self._start_worker(cfg)

    def _start_worker(self, camera: dict[str, Any]) -> None:
        cid = int(camera["id"])
        try:
            worker = CameraWorker(camera, self.settings, self.mqtt,
                                  self.hardware, self.object_detector)
            worker.start()
            with self._lock:
                self._workers[cid] = worker
            log.info("camera %s (%s): worker started", cid, camera.get("name"))
        except Exception:  # noqa: BLE001 - one bad camera must not kill the engine
            log.exception("camera %s: failed to start worker", cid)

    def _stop_worker(self, camera_id: int) -> None:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker is None:
            return
        try:
            worker.stop()
        except Exception:  # noqa: BLE001
            log.exception("camera %s: error stopping worker", camera_id)

    def reload_cameras(self) -> None:
        cameras = fetch_cameras(self.settings, self.stop_event)
        if cameras or not self.stop_event.is_set():
            self.apply_cameras(cameras)

    def restart_camera(self, camera_id: int) -> None:
        with self._lock:
            cfg = next((c for c in self._cameras
                        if int(c.get("id", -1)) == camera_id and c.get("enabled", True)), None)
        self._stop_worker(camera_id)
        if cfg is not None:
            self._start_worker(cfg)
        else:
            log.warning("restart_camera: camera %s not in current config", camera_id)

    # -- MQTT commands -------------------------------------------------------------

    def on_command(self, topic: str, payload: dict[str, Any]) -> None:
        action = payload.get("action")
        camera_id = payload.get("camera_id")
        log.info("Command received: %s (camera_id=%s)", action, camera_id)
        if action in ("reload_cameras", "reload_zones"):
            # Both re-read the full config from the backend (zones are embedded).
            threading.Thread(target=self.reload_cameras, daemon=True,
                             name="reload-cameras").start()
        elif action == "restart_camera" and camera_id is not None:
            threading.Thread(target=self.restart_camera, args=(int(camera_id),),
                             daemon=True, name=f"restart-{camera_id}").start()
        elif action == "ptz":
            log.info("PTZ command ignored: PTZ is handled by the backend (ONVIF)")
        else:
            log.warning("Unknown engine command: %r", payload)

    # -- lifecycle -------------------------------------------------------------------

    def run(self) -> None:
        for sub in ("recordings", "events", "snapshots"):
            try:
                os.makedirs(os.path.join(self.settings.media_root, sub), exist_ok=True)
            except OSError:
                log.exception("Cannot create %s under MEDIA_ROOT", sub)

        if not self.mqtt.connect(stop_event=self.stop_event):
            return  # interrupted during startup
        self.mqtt.publish_json(HARDWARE_TOPIC, self.hardware.to_payload(), retain=True)
        self.mqtt.subscribe(COMMAND_TOPIC, self.on_command)

        cameras = fetch_cameras(self.settings, self.stop_event)
        self.apply_cameras(cameras)
        self.retention.start()

        log.info("Engine running with %d workers (decode=%s, inference=%s)",
                 len(self._workers), self.hardware.selected_decode,
                 self.hardware.selected_inference)
        while not self.stop_event.wait(1.0):
            pass
        self.shutdown()

    def shutdown(self) -> None:
        log.info("Shutting down: stopping workers, ffmpeg children and loops")
        self.retention.stop()
        with self._lock:
            worker_ids = list(self._workers)
        for cid in worker_ids:
            self._stop_worker(cid)
        self.mqtt.close()
        log.info("Shutdown complete")


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    log.info("Horus video-engine starting (backend=%s, media=%s)",
             settings.backend_url, settings.media_root)

    # Must be set before any cv2.VideoCapture is opened (FFMPEG backend reads it).
    hardware = detect_hardware()
    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        opencv_capture_options(hardware.selected_decode),
    )

    engine = Engine(settings, hardware=hardware)

    def _signal_handler(signum: int, _frame: Any) -> None:
        log.info("Received signal %s; initiating clean shutdown", signum)
        engine.stop_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    engine.run()


if __name__ == "__main__":
    main()
