"""Segment filename parsing + event-window overlap selection (pure)."""
from __future__ import annotations

from datetime import datetime

from engine.recorder import (
    overlaps_any,
    overlaps_window,
    parse_segment_start,
    prune_windows,
    select_segments,
)


class TestParseSegmentStart:
    def test_parses_local_clock(self) -> None:
        path = "/media/recordings/1/2026-06-10/12-30-45.mp4"
        expected = datetime.strptime("2026-06-10 12:30:45", "%Y-%m-%d %H:%M:%S").timestamp()
        assert parse_segment_start(path) == expected

    def test_rejects_bad_names(self) -> None:
        assert parse_segment_start("/media/recordings/1/2026-06-10/notes.txt") is None
        assert parse_segment_start("/media/recordings/1/junkdir/12-30-45.mp4") is None
        assert parse_segment_start("/media/recordings/1/2026-06-10/25-99-99.mp4") is None


class TestOverlap:
    def test_closed_window(self) -> None:
        window = (100.0, 200.0)
        assert overlaps_window(150, 180, window)        # inside
        assert overlaps_window(50, 101, window)         # straddles start
        assert overlaps_window(199, 250, window)        # straddles end
        assert not overlaps_window(0, 100, window)      # touches, no overlap
        assert not overlaps_window(200, 300, window)

    def test_open_window_keeps_everything_after_start(self) -> None:
        window = (100.0, None)
        assert overlaps_window(150, 180, window)
        assert overlaps_window(90, 101, window)
        assert not overlaps_window(0, 99, window)

    def test_overlaps_any(self) -> None:
        windows = [(100.0, 200.0), (500.0, None)]
        assert overlaps_any(150, 160, windows)
        assert overlaps_any(490, 510, windows)
        assert not overlaps_any(300, 400, windows)


class TestSelectSegments:
    SEGMENTS = [
        ("/r/c.mp4", 60.0, 90.0),
        ("/r/a.mp4", 0.0, 30.0),
        ("/r/b.mp4", 30.0, 60.0),
        ("/r/d.mp4", 90.0, 120.0),
    ]

    def test_selects_overlapping_sorted_by_start(self) -> None:
        # window 45..95 overlaps b, c, d (pre-buffer included by the caller)
        assert select_segments(self.SEGMENTS, 45.0, 95.0) == \
            ["/r/b.mp4", "/r/c.mp4", "/r/d.mp4"]

    def test_no_overlap(self) -> None:
        assert select_segments(self.SEGMENTS, 500.0, 600.0) == []


class TestPruneWindows:
    def test_drops_old_closed_keeps_open_and_recent(self) -> None:
        windows = [(0.0, 10.0), (0.0, None), (50.0, 100.0)]
        assert prune_windows(windows, before=40.0) == [(0.0, None), (50.0, 100.0)]
