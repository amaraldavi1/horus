"""Motion detection: MOG2 background subtraction gated by zone masks.

Pure logic (mask building, area thresholds, dwell accounting) is kept in
standalone functions/classes so it can be unit-tested without a camera.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import cv2
import numpy as np

log = logging.getLogger("engine.motion")

Polygon = Sequence[Sequence[float]]  # normalized 0..1 [[x, y], ...]


# ---------------------------------------------------------------------------
# Pure mask math (unit-tested)
# ---------------------------------------------------------------------------

def polygon_to_pixels(polygon: Polygon, width: int, height: int) -> np.ndarray:
    """Convert normalized 0..1 polygon to int32 pixel coordinates."""
    pts = np.array(
        [[min(max(float(x), 0.0), 1.0) * (width - 1),
          min(max(float(y), 0.0), 1.0) * (height - 1)] for x, y in polygon],
        dtype=np.float64,
    )
    return np.rint(pts).astype(np.int32)


def build_zone_mask(zones: Sequence[dict[str, Any]], width: int, height: int) -> np.ndarray:
    """Build the combined uint8 mask (255 = analyse, 0 = ignore).

    Rules (per spec):
      * include zones are OR'd together;
      * exclude zones are subtracted afterwards;
      * no include zones => the full frame is analysed (minus excludes).
    """
    includes = [z for z in zones if z.get("kind") == "include" and z.get("polygon")]
    excludes = [z for z in zones if z.get("kind") == "exclude" and z.get("polygon")]

    if includes:
        mask = np.zeros((height, width), dtype=np.uint8)
        for zone in includes:
            cv2.fillPoly(mask, [polygon_to_pixels(zone["polygon"], width, height)], 255)
    else:
        mask = np.full((height, width), 255, dtype=np.uint8)

    for zone in excludes:
        cv2.fillPoly(mask, [polygon_to_pixels(zone["polygon"], width, height)], 0)
    return mask


def sensitivity_to_threshold(sensitivity: float) -> int:
    """Map sensitivity 0..100 (higher = more sensitive) to a binarization
    threshold for the MOG2 foreground mask (which contains 0/127/255)."""
    sensitivity = min(max(float(sensitivity), 0.0), 100.0)
    return int(round(250 - sensitivity * 2.2))  # 100 -> 30, 0 -> 250


def area_exceeds(motion_pixels: int, frame_pixels: int, min_area: float) -> bool:
    """min_area is a fraction of the *frame* area (e.g. 0.005 = 0.5%)."""
    if frame_pixels <= 0:
        return False
    return (motion_pixels / frame_pixels) >= max(float(min_area), 0.0)


class DwellTracker:
    """Requires motion to be sustained for >= dwell_ms before firing."""

    def __init__(self, dwell_ms: float) -> None:
        self.dwell_ms = max(float(dwell_ms), 0.0)
        self._first_seen_ms: float | None = None

    def update(self, motion_now: bool, now_ms: float) -> bool:
        """Feed one sample; returns True when motion has dwelled long enough."""
        if not motion_now:
            self._first_seen_ms = None
            return False
        if self._first_seen_ms is None:
            self._first_seen_ms = now_ms
        return (now_ms - self._first_seen_ms) >= self.dwell_ms


# ---------------------------------------------------------------------------
# Stateful detector (thin I/O-free wrapper around cv2 primitives)
# ---------------------------------------------------------------------------

@dataclass
class CompiledZone:
    zone_id: int | None
    mask: np.ndarray
    threshold: int
    min_area: float
    dwell: DwellTracker


@dataclass
class MotionResult:
    fired: bool = False              # sustained motion (dwell satisfied)
    raw_motion: bool = False         # instantaneous motion this frame
    zone_id: int | None = None
    area_fraction: float = 0.0
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)


_DEFAULT_ZONE = {"id": None, "kind": "include", "polygon": None,
                 "sensitivity": 25, "min_area": 0.005, "dwell_ms": 500}


class MotionDetector:
    """Per-camera motion detector. Call ``process(frame_bgr, now_ms)``."""

    def __init__(self, zones: Sequence[dict[str, Any]], frame_size: tuple[int, int]) -> None:
        self._width, self._height = frame_size
        self._subtractor = cv2.createBackgroundSubtractorMOG2(
            history=400, varThreshold=16, detectShadows=True
        )
        self._global_mask = build_zone_mask(zones, self._width, self._height)
        self._zones = self._compile_zones(zones)

    def _compile_zones(self, zones: Sequence[dict[str, Any]]) -> list[CompiledZone]:
        includes = [z for z in zones if z.get("kind") == "include" and z.get("polygon")]
        if not includes:
            includes = [dict(_DEFAULT_ZONE)]
        compiled: list[CompiledZone] = []
        for zone in includes:
            if zone.get("polygon"):
                mask = np.zeros((self._height, self._width), dtype=np.uint8)
                cv2.fillPoly(mask, [polygon_to_pixels(zone["polygon"], self._width, self._height)], 255)
                mask = cv2.bitwise_and(mask, self._global_mask)
            else:
                mask = self._global_mask
            compiled.append(CompiledZone(
                zone_id=zone.get("id"),
                mask=mask,
                threshold=sensitivity_to_threshold(zone.get("sensitivity", 25)),
                min_area=float(zone.get("min_area", 0.005)),
                dwell=DwellTracker(zone.get("dwell_ms", 500)),
            ))
        return compiled

    def process(self, frame_bgr: np.ndarray, now_ms: float) -> MotionResult:
        if frame_bgr.shape[1] != self._width or frame_bgr.shape[0] != self._height:
            frame_bgr = cv2.resize(frame_bgr, (self._width, self._height))
        fg = self._subtractor.apply(frame_bgr)
        fg = cv2.bitwise_and(fg, self._global_mask)
        frame_pixels = self._width * self._height

        result = MotionResult()
        for zone in self._zones:
            zone_fg = cv2.bitwise_and(fg, zone.mask)
            _, binary = cv2.threshold(zone_fg, zone.threshold, 255, cv2.THRESH_BINARY)
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            min_pixels = zone.min_area * frame_pixels
            boxes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) >= min_pixels]
            motion_pixels = int(np.count_nonzero(binary))
            motion_now = bool(boxes) and area_exceeds(motion_pixels, frame_pixels, zone.min_area)
            sustained = zone.dwell.update(motion_now, now_ms)
            if motion_now:
                result.raw_motion = True
                fraction = motion_pixels / frame_pixels
                if fraction > result.area_fraction:
                    result.area_fraction = fraction
                result.boxes.extend(boxes)
            if sustained and not result.fired:
                result.fired = True
                result.zone_id = zone.zone_id
        return result
