"""CameraWorker: one camera's full pipeline (detection + events + recording).

A worker owns:
  * the detection stream (sub_url, falling back to main_url) via OpenCV/FFMPEG
  * a MotionDetector (zone-masked MOG2) sampled at detect_fps
  * an optional shared ObjectDetector (ONNX)
  * an EventManager (start/update/end publishing, snapshots, clips)
  * a Recorder (ffmpeg remux segmenter + ring buffer)
  * retained status publishing (CONTRACTS §1.2) with reconnect backoff

A worker failure never propagates: the loop catches everything, publishes an
error status and retries with exponential backoff.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import cv2

from engine.config import Settings
from engine.events import EventManager
from engine.hardware import HardwareReport, status_decode_name, status_detect_name
from engine.motion import MotionDetector
from engine.mqtt import MqttClient
from engine.objects import ObjectDetector
from engine.recorder import Recorder

log = logging.getLogger("engine.worker")

DETECT_WIDTH = 640          # frames are downscaled to this width for analysis
MIN_OBJECT_CONFIDENCE = 0.4


def _iso_to_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class CameraWorker:
    """Runs the detection loop in its own thread; owns the camera's Recorder."""

    def __init__(self, camera: dict[str, Any], settings: Settings, mqtt: MqttClient,
                 hardware: HardwareReport, object_detector: ObjectDetector | None) -> None:
        self.camera = camera
        self.camera_id = int(camera["id"])
        self._settings = settings
        self._mqtt = mqtt
        self._hardware = hardware
        self._object_detector = object_detector
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._recorder = Recorder(
            camera, settings.media_root,
            publish_segment=self._publish_segment,
            decode_path=hardware.selected_decode,
        )
        self._events = EventManager(
            camera_id=self.camera_id,
            media_root=settings.media_root,
            publish=self._publish_event,
            clip_builder=self._recorder.build_event_clip,
            quiet_s=settings.event_quiet_s,
        )

        self._state = "connecting"
        self._error: str | None = None
        self._fps = 0.0
        self._last_status_at = 0.0
        self._last_status_key: tuple[Any, ...] | None = None

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self._recorder.start()
        self._thread = threading.Thread(
            target=self._run, name=f"camera-{self.camera_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
            self._thread = None
        try:
            self._events.close()
        except Exception:  # noqa: BLE001
            log.exception("camera %s: error closing event manager", self.camera_id)
        self._recorder.stop()
        self._publish_status(state="offline", force=True)

    # -- publishing ------------------------------------------------------------

    def _publish_event(self, payload: dict[str, Any]) -> None:
        phase = payload.get("phase")
        try:  # feed event windows to the recorder (pre-buffer keep logic)
            if phase == "start":
                self._recorder.notify_event_start(_iso_to_epoch(payload["started_at"]))
            elif phase == "end" and payload.get("ended_at"):
                self._recorder.notify_event_end(
                    _iso_to_epoch(payload["started_at"]), _iso_to_epoch(payload["ended_at"]))
        except Exception:  # noqa: BLE001
            log.exception("camera %s: recorder window notify failed", self.camera_id)
        self._mqtt.publish_json(f"horus/events/{self.camera_id}", payload)
        self._publish_status(force=True)

    def _publish_segment(self, payload: dict[str, Any]) -> None:
        ok = self._mqtt.connected and self._mqtt.publish_json(
            f"horus/recordings/{self.camera_id}", payload)
        if not ok:  # HTTP fallback per CONTRACTS §2
            try:
                import httpx
                httpx.post(
                    f"{self._settings.backend_url}/internal/recordings",
                    json=payload,
                    headers={"X-Internal-Token": self._settings.internal_api_token},
                    timeout=10.0,
                ).raise_for_status()
            except Exception as exc:  # noqa: BLE001
                log.warning("camera %s: segment publish failed via MQTT and HTTP: %s",
                            self.camera_id, exc)

    def _publish_status(self, state: str | None = None, error: str | None = None,
                        force: bool = False) -> None:
        if state is not None:
            self._state = state
            self._error = error
        now = time.time()
        key = (self._state, self._error, self._recorder.recording,
               self._events.in_event, round(self._fps))
        changed = key != self._last_status_key
        if not force and not changed and (now - self._last_status_at) < self._settings.status_interval_s:
            return
        self._last_status_at = now
        self._last_status_key = key
        payload = {
            "camera_id": self.camera_id,
            "state": self._state,
            "recording": self._recorder.recording,
            "in_event": self._events.in_event,
            "fps": round(self._fps, 1),
            "decode_path": status_decode_name(self._hardware.selected_decode),
            "detect_path": status_detect_name(
                self._hardware.selected_inference,
                bool(self.camera.get("detect_objects")) and self._object_detector is not None,
            ),
            "error": self._error,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        self._mqtt.publish_json(f"horus/status/{self.camera_id}", payload, retain=True)

    # -- detection loop ----------------------------------------------------------

    def _open_capture(self) -> tuple[cv2.VideoCapture | None, str]:
        urls = [u for u in (self.camera.get("sub_url"), self.camera.get("main_url")) if u]
        for url in urls:
            try:
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    return cap, url
                cap.release()
            except Exception:  # noqa: BLE001
                log.exception("camera %s: VideoCapture(%s) crashed", self.camera_id, url)
        return None, ""

    def _run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            self._publish_status(state="connecting", force=True)
            cap, url = self._open_capture()
            if cap is None:
                self._publish_status(state="offline", error="stream unreachable", force=True)
                log.warning("camera %s: unreachable; retrying in %.0fs", self.camera_id, backoff)
                if self._stop.wait(backoff):
                    break
                backoff = min(backoff * 2, 60.0)
                continue
            backoff = 2.0
            log.info("camera %s: detection stream opened (%s)", self.camera_id,
                     "sub" if url == self.camera.get("sub_url") else "main")
            try:
                self._detection_loop(cap)
            except Exception as exc:  # noqa: BLE001
                log.exception("camera %s: detection loop crashed", self.camera_id)
                self._publish_status(state="error", error=str(exc)[:200], force=True)
            finally:
                try:
                    cap.release()
                except Exception:  # noqa: BLE001
                    pass
            if not self._stop.is_set():
                self._events.close()  # finalize any open event before reconnecting
                self._publish_status(state="offline", error="stream lost", force=True)
                if self._stop.wait(backoff):
                    break
                backoff = min(backoff * 2, 60.0)

    def _detection_loop(self, cap: cv2.VideoCapture) -> None:
        detect_fps = max(float(self.camera.get("detect_fps") or 5), 0.5)
        sample_interval = 1.0 / detect_fps
        detector: MotionDetector | None = None
        objects_enabled = bool(self.camera.get("detect_objects")) and self._object_detector is not None
        next_sample = 0.0
        frames = 0
        fps_window_start = time.time()
        consecutive_failures = 0

        self._publish_status(state="online", error=None, force=True)
        while not self._stop.is_set():
            ok, frame = cap.read()
            now = time.time()
            if not ok or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= 30:
                    return  # stream lost -> outer loop reconnects
                time.sleep(0.05)
                continue
            consecutive_failures = 0
            frames += 1
            if now - fps_window_start >= 5.0:
                self._fps = frames / (now - fps_window_start)
                frames, fps_window_start = 0, now

            if now < next_sample:
                self._events.tick(now)
                self._publish_status()
                continue
            next_sample = now + sample_interval

            small = self._downscale(frame)
            if detector is None:
                detector = MotionDetector(
                    self.camera.get("zones") or [],
                    (small.shape[1], small.shape[0]),
                )
            result = detector.process(small, now * 1000.0)
            if result.fired:
                self._events.on_motion(frame, result.zone_id, now)
                if objects_enabled:
                    detections = [d for d in self._object_detector.detect(frame)
                                  if d.confidence >= MIN_OBJECT_CONFIDENCE]
                    self._events.on_objects(detections, now)
            self._events.tick(now)
            self._publish_status()

    @staticmethod
    def _downscale(frame: Any) -> Any:
        h, w = frame.shape[:2]
        if w <= DETECT_WIDTH:
            return frame
        scale = DETECT_WIDTH / w
        return cv2.resize(frame, (DETECT_WIDTH, max(1, int(h * scale))))
