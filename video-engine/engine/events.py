"""Event lifecycle (CONTRACTS §1.1): start -> update -> end.

The EventManager has *no* knowledge of MQTT or ffmpeg: it gets a ``publish``
callable and a ``clip_builder`` callable injected, which keeps the state
machine unit-testable.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np

log = logging.getLogger("engine.events")

PublishFn = Callable[[dict[str, Any]], None]
# clip_builder(event_id, start_epoch, end_epoch) -> (clip_path | None, duration_s | None)
ClipBuilderFn = Callable[[str, float, float], tuple[str | None, float | None]]


def utc_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def snapshot_path_for(media_root: str, camera_id: int, event_id: str, epoch: float) -> str:
    date_dir = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(media_root, "snapshots", str(camera_id), date_dir, f"{event_id}.webp")


def save_webp_snapshot(frame_bgr: np.ndarray, path: str, quality: int = 80) -> bool:
    """Save a BGR frame as WebP via Pillow. Returns False on any failure."""
    try:
        from PIL import Image
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Image.fromarray(frame_bgr[:, :, ::-1]).save(path, format="WEBP", quality=quality)
        return True
    except Exception:  # noqa: BLE001
        log.exception("Failed to write snapshot %s", path)
        return False


@dataclass
class ActiveEvent:
    event_id: str
    camera_id: int
    started_at: float
    last_motion_at: float
    zone_id: int | None = None
    type: str = "motion"            # upgraded to "object" if a label appears
    label: str | None = None
    confidence: float | None = None
    snapshot_path: str | None = None
    published_labels: set[str] = field(default_factory=set)


class EventManager:
    """One per camera. Thread-confined to the worker's detection loop."""

    def __init__(self, camera_id: int, media_root: str, publish: PublishFn,
                 clip_builder: ClipBuilderFn, quiet_s: float = 5.0) -> None:
        self._camera_id = camera_id
        self._media_root = media_root
        self._publish = publish
        self._clip_builder = clip_builder
        self._quiet_s = quiet_s
        self.active: ActiveEvent | None = None

    @property
    def in_event(self) -> bool:
        return self.active is not None

    # -- inputs from the detection loop ---------------------------------------

    def on_motion(self, frame_bgr: np.ndarray, zone_id: int | None,
                  now: float | None = None) -> None:
        """Called when *sustained* motion is detected (dwell already applied)."""
        now = now if now is not None else time.time()
        if self.active is None:
            self._start(frame_bgr, zone_id, now)
        else:
            self.active.last_motion_at = now

    def on_objects(self, detections: list[Any], now: float | None = None) -> None:
        """Refine the open event with object labels (best confidence wins)."""
        if self.active is None or not detections:
            return
        now = now if now is not None else time.time()
        self.active.last_motion_at = now
        best = max(detections, key=lambda d: d.confidence)
        changed = False
        if self.active.type != "object" or (self.active.confidence or 0) < best.confidence:
            self.active.type = "object"
            self.active.label = best.label
            self.active.confidence = round(float(best.confidence), 3)
            changed = best.label not in self.active.published_labels
        if changed:
            self.active.published_labels.add(best.label)
            self._publish(self._payload(phase="update"))

    def tick(self, now: float | None = None) -> None:
        """Close the event after the quiet period elapses without motion."""
        now = now if now is not None else time.time()
        if self.active is not None and (now - self.active.last_motion_at) >= self._quiet_s:
            self._end(now)

    def close(self) -> None:
        """Force-close (camera lost / shutdown)."""
        if self.active is not None:
            self._end(time.time())

    # -- internals -------------------------------------------------------------

    def _start(self, frame_bgr: np.ndarray, zone_id: int | None, now: float) -> None:
        event = ActiveEvent(
            event_id=str(uuid.uuid4()),
            camera_id=self._camera_id,
            started_at=now,
            last_motion_at=now,
            zone_id=zone_id,
        )
        path = snapshot_path_for(self._media_root, self._camera_id, event.event_id, now)
        if save_webp_snapshot(frame_bgr, path):
            event.snapshot_path = path
        self.active = event
        log.info("camera %s: event %s started (zone=%s)", self._camera_id, event.event_id, zone_id)
        self._publish(self._payload(phase="start"))

    def _end(self, now: float) -> None:
        event = self.active
        if event is None:
            return
        self.active = None
        clip_path: str | None = None
        duration: float | None = round(now - event.started_at, 1)
        try:
            clip_path, clip_duration = self._clip_builder(event.event_id, event.started_at, now)
            if clip_duration:
                duration = round(clip_duration, 1)
        except Exception:  # noqa: BLE001
            log.exception("camera %s: clip build failed for event %s",
                          self._camera_id, event.event_id)
        log.info("camera %s: event %s ended (%.1fs, clip=%s)",
                 self._camera_id, event.event_id, duration or 0.0, clip_path)
        self._publish(self._payload(phase="end", event=event, ended_at=now,
                                    clip_path=clip_path, duration_s=duration))

    def _payload(self, phase: str, event: ActiveEvent | None = None,
                 ended_at: float | None = None, clip_path: str | None = None,
                 duration_s: float | None = None) -> dict[str, Any]:
        event = event or self.active
        assert event is not None
        return {
            "phase": phase,
            "event_id": event.event_id,
            "camera_id": event.camera_id,
            "type": event.type,
            "label": event.label,
            "confidence": event.confidence,
            "zone_id": event.zone_id,
            "started_at": utc_iso(event.started_at),
            "ended_at": utc_iso(ended_at) if ended_at is not None else None,
            "snapshot_path": event.snapshot_path,
            "clip_path": clip_path,
            "duration_s": duration_s,
        }
