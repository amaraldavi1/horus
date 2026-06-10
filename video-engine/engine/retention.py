"""Retention: age-based cleanup + disk-pressure rotation.

Every cycle (default 5 min):
  * delete continuous recordings older than ``retention_days_continuous``
  * delete event clips + snapshots older than ``retention_days_event``
  * if disk usage of MEDIA_ROOT >= MAX_DISK_USAGE_PCT, delete the *oldest
    continuous* segments first until back below the threshold
  * prune empty date directories

Selection logic is pure (lists of (path, mtime, size) tuples in, lists of
paths out) so it is unit-testable without touching a filesystem.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from typing import Any, Callable, Iterable

log = logging.getLogger("engine.retention")

# (path, mtime_epoch, size_bytes)
FileInfo = tuple[str, float, int]


# ---------------------------------------------------------------------------
# Pure selection logic (unit-tested)
# ---------------------------------------------------------------------------

def select_expired(files: Iterable[FileInfo], now: float, retention_days: float) -> list[str]:
    """Paths whose mtime is older than ``retention_days``. A retention of 0 or
    less means 'keep forever' (defensive: never mass-delete on bad config)."""
    if retention_days <= 0:
        return []
    cutoff = now - retention_days * 86400.0
    return [path for path, mtime, _ in files if mtime < cutoff]


def select_for_disk_pressure(continuous_files: Iterable[FileInfo],
                             bytes_to_free: int) -> list[str]:
    """Oldest-first continuous segments whose cumulative size covers
    ``bytes_to_free``. Empty list if nothing needs freeing."""
    if bytes_to_free <= 0:
        return []
    chosen: list[str] = []
    freed = 0
    for path, _, size in sorted(continuous_files, key=lambda f: f[1]):
        chosen.append(path)
        freed += size
        if freed >= bytes_to_free:
            break
    return chosen


def bytes_to_free_for_target(total: int, used: int, max_pct: float,
                             headroom_pct: float = 5.0) -> int:
    """How many bytes to delete so usage drops below max_pct minus headroom."""
    if total <= 0:
        return 0
    used_pct = used / total * 100.0
    if used_pct < max_pct:
        return 0
    target_pct = max(max_pct - headroom_pct, 0.0)
    return int(used - total * target_pct / 100.0)


# ---------------------------------------------------------------------------
# Filesystem walking + loop
# ---------------------------------------------------------------------------

def scan_files(root: str, suffix: str | None = None) -> list[FileInfo]:
    results: list[FileInfo] = []
    if not os.path.isdir(root):
        return results
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if suffix and not name.endswith(suffix):
                continue
            path = os.path.join(dirpath, name)
            try:
                stat = os.stat(path)
                results.append((path, stat.st_mtime, stat.st_size))
            except OSError:
                continue
    return results


def remove_empty_dirs(root: str) -> int:
    """Remove empty directories below (but not including) root."""
    removed = 0
    if not os.path.isdir(root):
        return 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root or dirnames or filenames:
            continue
        try:
            os.rmdir(dirpath)
            removed += 1
        except OSError:
            pass
    return removed


class RetentionLoop:
    """Background thread enforcing retention for all cameras."""

    def __init__(self, media_root: str, max_disk_usage_pct: float,
                 cameras_provider: Callable[[], list[dict[str, Any]]],
                 interval_s: float = 300.0,
                 min_age_s: float = 300.0) -> None:
        self._media_root = media_root
        self._max_pct = max_disk_usage_pct
        self._cameras_provider = cameras_provider
        self._interval_s = interval_s
        self._min_age_s = min_age_s  # never touch files this fresh (open segments)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="retention", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def run_once(self) -> None:
        """One full retention pass (also used directly by tests/CLI)."""
        now = time.time()
        cameras = []
        try:
            cameras = self._cameras_provider()
        except Exception:  # noqa: BLE001
            log.exception("retention: cameras provider failed; age pass skipped")

        for camera in cameras:
            cid = str(camera.get("id"))
            self._delete_paths(select_expired(
                self._fresh_filter(scan_files(os.path.join(self._media_root, "recordings", cid)), now),
                now, float(camera.get("retention_days_continuous") or 0)), "continuous")
            event_days = float(camera.get("retention_days_event") or 0)
            self._delete_paths(select_expired(
                scan_files(os.path.join(self._media_root, "events", cid)), now, event_days), "event clip")
            self._delete_paths(select_expired(
                scan_files(os.path.join(self._media_root, "snapshots", cid)), now, event_days), "snapshot")

        self._disk_pressure_pass(now)

        for sub in ("recordings", "events", "snapshots"):
            removed = remove_empty_dirs(os.path.join(self._media_root, sub))
            if removed:
                log.info("retention: removed %d empty dirs under %s", removed, sub)

    # -- internals ---------------------------------------------------------------

    def _fresh_filter(self, files: list[FileInfo], now: float) -> list[FileInfo]:
        return [f for f in files if (now - f[1]) > self._min_age_s]

    def _disk_pressure_pass(self, now: float) -> None:
        try:
            usage = shutil.disk_usage(self._media_root)
        except OSError:
            log.exception("retention: disk_usage(%s) failed", self._media_root)
            return
        to_free = bytes_to_free_for_target(usage.total, usage.used, self._max_pct)
        if to_free <= 0:
            return
        used_pct = usage.used / usage.total * 100.0
        log.warning("retention: disk at %.1f%% (>= %.0f%%); freeing ~%d MiB of "
                    "oldest continuous segments", used_pct, self._max_pct, to_free // 2**20)
        continuous = self._fresh_filter(
            scan_files(os.path.join(self._media_root, "recordings"), suffix=".mp4"), now)
        victims = select_for_disk_pressure(continuous, to_free)
        self._delete_paths(victims, "disk-pressure")
        if not victims:
            log.error("retention: disk over threshold but no continuous segments "
                      "eligible for deletion")

    def _delete_paths(self, paths: list[str], reason: str) -> None:
        for path in paths:
            try:
                size = os.path.getsize(path)
                os.remove(path)
                log.info("retention: deleted %s (%s, %d bytes)", path, reason, size)
            except OSError:
                pass

    def _run(self) -> None:
        # Small initial delay so startup isn't competing with camera spin-up.
        self._stop.wait(30.0)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("retention pass crashed; will retry next cycle")
            self._stop.wait(self._interval_s)
