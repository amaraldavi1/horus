"""Zone-mask math + motion threshold/dwell logic (pure, no camera)."""
from __future__ import annotations

import numpy as np

from engine.motion import (
    DwellTracker,
    area_exceeds,
    build_zone_mask,
    polygon_to_pixels,
    sensitivity_to_threshold,
)

W, H = 100, 80
SQUARE = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]  # central block
LEFT = [[0.0, 0.0], [0.4, 0.0], [0.4, 1.0], [0.0, 1.0]]
RIGHT = [[0.6, 0.0], [1.0, 0.0], [1.0, 1.0], [0.6, 1.0]]


def zone(kind: str, polygon: list[list[float]], **extra) -> dict:
    return {"id": 1, "kind": kind, "polygon": polygon,
            "sensitivity": 25, "min_area": 0.005, "dwell_ms": 500, **extra}


class TestPolygonToPixels:
    def test_scales_to_frame(self) -> None:
        pts = polygon_to_pixels([[0.0, 0.0], [1.0, 1.0]], W, H)
        assert pts.tolist() == [[0, 0], [W - 1, H - 1]]
        assert pts.dtype == np.int32

    def test_clamps_out_of_range(self) -> None:
        pts = polygon_to_pixels([[-0.5, 2.0]], W, H)
        assert pts.tolist() == [[0, H - 1]]


class TestBuildZoneMask:
    def test_no_zones_full_frame(self) -> None:
        mask = build_zone_mask([], W, H)
        assert mask.shape == (H, W)
        assert np.all(mask == 255)

    def test_include_zone_limits_area(self) -> None:
        mask = build_zone_mask([zone("include", SQUARE)], W, H)
        assert mask[H // 2, W // 2] == 255       # center inside
        assert mask[0, 0] == 0                   # corner outside
        assert 0 < np.count_nonzero(mask) < W * H

    def test_include_zones_are_ord(self) -> None:
        mask = build_zone_mask([zone("include", LEFT), zone("include", RIGHT)], W, H)
        assert mask[H // 2, int(0.2 * W)] == 255   # in LEFT
        assert mask[H // 2, int(0.8 * W)] == 255   # in RIGHT
        assert mask[H // 2, W // 2] == 0           # gap between zones

    def test_exclude_subtracted_from_include(self) -> None:
        mask = build_zone_mask([zone("include", SQUARE), zone("exclude", LEFT)], W, H)
        assert mask[H // 2, int(0.2 * W)] == 0     # excluded strip wins
        assert mask[H // 2, int(0.8 * W)] == 255   # rest of include stays

    def test_exclude_only_means_full_frame_minus_exclude(self) -> None:
        mask = build_zone_mask([zone("exclude", LEFT)], W, H)
        assert mask[H // 2, int(0.2 * W)] == 0
        assert mask[H // 2, int(0.8 * W)] == 255


class TestThresholds:
    def test_sensitivity_monotonic(self) -> None:
        assert sensitivity_to_threshold(100) < sensitivity_to_threshold(50) < sensitivity_to_threshold(0)

    def test_area_exceeds_fraction_of_frame(self) -> None:
        frame_pixels = W * H
        assert area_exceeds(int(0.01 * frame_pixels), frame_pixels, 0.005)
        assert not area_exceeds(int(0.001 * frame_pixels), frame_pixels, 0.005)
        assert not area_exceeds(10, 0, 0.005)  # degenerate frame


class TestDwellTracker:
    def test_fires_only_after_dwell(self) -> None:
        dwell = DwellTracker(500)
        assert not dwell.update(True, 1000.0)    # first sighting
        assert not dwell.update(True, 1300.0)    # 300ms < 500ms
        assert dwell.update(True, 1600.0)        # 600ms >= 500ms

    def test_gap_resets_dwell(self) -> None:
        dwell = DwellTracker(500)
        assert not dwell.update(True, 1000.0)
        assert not dwell.update(False, 1300.0)   # motion gap resets
        assert not dwell.update(True, 1700.0)
        assert not dwell.update(True, 2100.0)    # only 400ms since reset
        assert dwell.update(True, 2300.0)

    def test_zero_dwell_fires_immediately(self) -> None:
        assert DwellTracker(0).update(True, 42.0)
