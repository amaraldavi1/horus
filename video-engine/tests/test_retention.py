"""Retention selection logic (pure functions, no filesystem/camera)."""
from __future__ import annotations

import os

from engine.retention import (
    bytes_to_free_for_target,
    remove_empty_dirs,
    select_expired,
    select_for_disk_pressure,
)

DAY = 86400.0
NOW = 1_750_000_000.0


def fi(path: str, age_days: float, size: int = 1000) -> tuple[str, float, int]:
    return (path, NOW - age_days * DAY, size)


class TestSelectExpired:
    def test_only_older_than_retention(self) -> None:
        files = [fi("old.mp4", 8), fi("edge.mp4", 6.9), fi("new.mp4", 1)]
        assert select_expired(files, NOW, retention_days=7) == ["old.mp4"]

    def test_zero_or_negative_retention_keeps_everything(self) -> None:
        files = [fi("a.mp4", 1000)]
        assert select_expired(files, NOW, retention_days=0) == []
        assert select_expired(files, NOW, retention_days=-1) == []

    def test_empty_input(self) -> None:
        assert select_expired([], NOW, retention_days=7) == []


class TestSelectForDiskPressure:
    def test_oldest_first_until_freed(self) -> None:
        files = [
            fi("mid.mp4", 5, size=400),
            fi("oldest.mp4", 9, size=400),
            fi("newest.mp4", 1, size=400),
        ]
        assert select_for_disk_pressure(files, bytes_to_free=700) == ["oldest.mp4", "mid.mp4"]

    def test_takes_everything_if_not_enough(self) -> None:
        files = [fi("a.mp4", 2, size=100), fi("b.mp4", 1, size=100)]
        assert select_for_disk_pressure(files, bytes_to_free=10_000) == ["a.mp4", "b.mp4"]

    def test_nothing_to_free(self) -> None:
        assert select_for_disk_pressure([fi("a.mp4", 2)], bytes_to_free=0) == []


class TestBytesToFreeForTarget:
    def test_below_threshold_frees_nothing(self) -> None:
        assert bytes_to_free_for_target(total=1000, used=800, max_pct=90) == 0

    def test_at_threshold_frees_down_to_headroom(self) -> None:
        # 90% used, target 85% -> free 5% of total
        assert bytes_to_free_for_target(total=1000, used=900, max_pct=90) == 50

    def test_degenerate_total(self) -> None:
        assert bytes_to_free_for_target(total=0, used=0, max_pct=90) == 0


class TestRemoveEmptyDirs:
    def test_removes_nested_empty_keeps_root_and_nonempty(self, tmp_path) -> None:
        root = tmp_path / "recordings"
        (root / "1" / "2026-01-01").mkdir(parents=True)          # empty chain
        keep = root / "2" / "2026-06-10"
        keep.mkdir(parents=True)
        (keep / "12-00-00.mp4").write_bytes(b"x")
        removed = remove_empty_dirs(str(root))
        assert removed == 2                                       # 2026-01-01 and 1
        assert root.is_dir()
        assert (keep / "12-00-00.mp4").exists()
        assert not (root / "1").exists()

    def test_missing_root(self) -> None:
        assert remove_empty_dirs(os.path.join("/nonexistent", "x")) == 0
