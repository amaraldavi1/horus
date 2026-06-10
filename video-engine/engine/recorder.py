"""Continuous remux recording + segment ring buffer + event clip assembly.

One ffmpeg subprocess per camera remuxes (``-c copy``, no re-encode) the main
stream into segmented mp4s under ``/media/recordings/{cid}/{YYYY-MM-DD}/``.

Recording modes:
  * continuous — every finished segment is kept and published (kind=continuous)
  * motion / object — the segmenter runs continuously into a small ring; the
    watcher only keeps segments overlapping an event window (which starts
    ``pre_buffer_s`` *before* the event) and deletes the rest. This is how the
    pre-event buffer works without re-encoding.
  * scheduled — schedule rules decide the effective mode per point in time
  * off — no recording at all

Pure decision logic (filename parsing, window overlap, segment selection) is
kept free of I/O for unit testing.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from engine import schedule as schedule_mod
from engine.hardware import ffmpeg_input_hwaccel_args

log = logging.getLogger("engine.recorder")

SEGMENT_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})\.mp4$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Window = (start_epoch, end_epoch | None while the event is still open)
Window = tuple[float, float | None]


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------

def parse_segment_start(path: str) -> float | None:
    """Epoch of a segment from ``.../{YYYY-MM-DD}/{HH-MM-SS}.mp4`` (local TZ,
    matching ffmpeg's -strftime behaviour). None if the name doesn't match."""
    name = os.path.basename(path)
    date_dir = os.path.basename(os.path.dirname(path))
    m = SEGMENT_RE.match(name)
    if not m or not DATE_RE.match(date_dir):
        return None
    try:
        dt = datetime.strptime(f"{date_dir} {m.group(1)}:{m.group(2)}:{m.group(3)}",
                               "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()  # naive -> local time, same clock ffmpeg used
    except ValueError:
        return None


def overlaps_window(seg_start: float, seg_end: float, window: Window) -> bool:
    w_start, w_end = window
    if w_end is None:  # still-open event: everything after w_start overlaps
        return seg_end > w_start
    return seg_start < w_end and seg_end > w_start


def overlaps_any(seg_start: float, seg_end: float, windows: list[Window]) -> bool:
    return any(overlaps_window(seg_start, seg_end, w) for w in windows)


def select_segments(segments: list[tuple[str, float, float]],
                    window_start: float, window_end: float) -> list[str]:
    """Pick segment paths overlapping [window_start, window_end), sorted by
    start time. ``segments`` items are (path, seg_start, seg_end)."""
    hits = [(start, path) for path, start, end in segments
            if overlaps_window(start, end, (window_start, window_end))]
    return [path for _, path in sorted(hits)]


def prune_windows(windows: list[Window], before: float) -> list[Window]:
    """Drop closed windows that ended before ``before``."""
    return [w for w in windows if w[1] is None or w[1] > before]


def effective_mode(camera: dict[str, Any], now_utc: datetime | None = None) -> str:
    """Resolve recording_mode, expanding 'scheduled' through the rules."""
    mode = camera.get("recording_mode", "off")
    if mode == "scheduled":
        return schedule_mod.active_mode(camera.get("schedule"), now_utc)
    return mode


def _utc_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class FinishedSegment:
    path: str
    start: float
    end: float
    size_bytes: int


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------

PublishSegmentFn = Callable[[dict[str, Any]], None]


class Recorder:
    """Owns the ffmpeg segmenter + watcher thread for one camera."""

    WATCH_INTERVAL_S = 2.0
    FINISHED_AGE_S = 3.0      # mtime stale for this long => segment closed
    DELETE_GRACE_S = 15.0     # extra slack before discarding non-event segments

    def __init__(self, camera: dict[str, Any], media_root: str,
                 publish_segment: PublishSegmentFn, decode_path: str = "cpu") -> None:
        self._camera = camera
        self._camera_id = int(camera["id"])
        self._media_root = media_root
        self._publish_segment = publish_segment
        self._decode_path = decode_path
        self._segment_s = int(camera.get("segment_s") or 30)
        self._pre_buffer_s = float(camera.get("pre_buffer_s") or 5)
        self._proc: subprocess.Popen[bytes] | None = None
        self._proc_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._windows: list[Window] = []
        self._windows_lock = threading.Lock()
        self._published: set[str] = set()
        self._backoff_s = 2.0
        self._next_start_at = 0.0

    # -- public API ------------------------------------------------------------

    @property
    def recording(self) -> bool:
        with self._proc_lock:
            return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._watch_loop, name=f"recorder-{self._camera_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._stop_ffmpeg()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def update_camera(self, camera: dict[str, Any]) -> None:
        """Apply a refreshed config; restarts ffmpeg if the URL changed."""
        url_changed = camera.get("main_url") != self._camera.get("main_url")
        self._camera = camera
        self._segment_s = int(camera.get("segment_s") or 30)
        self._pre_buffer_s = float(camera.get("pre_buffer_s") or 5)
        if url_changed:
            self._stop_ffmpeg()

    def notify_event_start(self, event_start: float) -> None:
        with self._windows_lock:
            self._windows.append((event_start - self._pre_buffer_s, None))

    def notify_event_end(self, event_start: float, event_end: float) -> None:
        with self._windows_lock:
            for i, (w_start, w_end) in enumerate(self._windows):
                if w_end is None and abs(w_start - (event_start - self._pre_buffer_s)) < 1.0:
                    self._windows[i] = (w_start, event_end)
                    return
            self._windows.append((event_start - self._pre_buffer_s, event_end))

    def build_event_clip(self, event_id: str, start: float, end: float) -> tuple[str | None, float | None]:
        """Concat (-c copy) the kept segments covering [start-pre_buffer, end]
        into /media/events/{cid}/{date}/{event_id}.mp4."""
        window_start = start - self._pre_buffer_s
        segments = [(s.path, s.start, s.end) for s in self._scan_segments()]
        chosen = select_segments(segments, window_start, end)
        if not chosen:
            log.warning("camera %s: no segments found for event %s clip",
                        self._camera_id, event_id)
            return None, None
        date_dir = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%d")
        out_dir = os.path.join(self._media_root, "events", str(self._camera_id), date_dir)
        out_path = os.path.join(out_dir, f"{event_id}.mp4")
        list_path = os.path.join(out_dir, f".{event_id}.txt")
        try:
            os.makedirs(out_dir, exist_ok=True)
            with open(list_path, "w", encoding="utf-8") as fh:
                for seg in chosen:
                    fh.write(f"file '{seg}'\n")
            cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
            if proc.returncode != 0 or not os.path.isfile(out_path):
                log.error("camera %s: clip concat failed for %s: %s",
                          self._camera_id, event_id, proc.stderr.strip()[:500])
                return None, None
            seg_starts = [s for p, s, e in segments if p in chosen]
            clip_start = min(seg_starts) if seg_starts else window_start
            return out_path, max(0.0, end - clip_start)
        except Exception:  # noqa: BLE001
            log.exception("camera %s: clip build crashed for event %s",
                          self._camera_id, event_id)
            return None, None
        finally:
            try:
                os.remove(list_path)
            except OSError:
                pass

    # -- ffmpeg management -------------------------------------------------------

    def _ffmpeg_cmd(self) -> list[str]:
        url = self._camera["main_url"]
        pattern = os.path.join(self._recordings_dir(), "%Y-%m-%d", "%H-%M-%S.mp4")
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
        cmd += ffmpeg_input_hwaccel_args(self._decode_path)
        if url.startswith("rtsp"):
            cmd += ["-rtsp_transport", "tcp"]
        cmd += [
            "-i", url,
            "-c", "copy", "-map", "0:v:0?", "-map", "0:a:0?",
            "-f", "segment",
            "-segment_time", str(self._segment_s),
            "-segment_format", "mp4",
            "-reset_timestamps", "1",
            "-strftime", "1",
            pattern,
        ]
        return cmd

    def _start_ffmpeg(self) -> None:
        self._ensure_date_dirs()
        try:
            with self._proc_lock:
                self._proc = subprocess.Popen(
                    self._ffmpeg_cmd(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
            log.info("camera %s: ffmpeg segmenter started (pid=%s)",
                     self._camera_id, self._proc.pid)
        except Exception:  # noqa: BLE001
            log.exception("camera %s: failed to spawn ffmpeg", self._camera_id)
            with self._proc_lock:
                self._proc = None

    def _stop_ffmpeg(self) -> None:
        with self._proc_lock:
            proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            log.info("camera %s: ffmpeg segmenter stopped", self._camera_id)
        except Exception:  # noqa: BLE001
            log.exception("camera %s: error stopping ffmpeg", self._camera_id)

    def _supervise_ffmpeg(self, mode: str) -> None:
        if mode == "off":
            if self.recording:
                self._stop_ffmpeg()
            return
        if self.recording:
            self._backoff_s = 2.0
            return
        with self._proc_lock:
            proc = self._proc
        if proc is not None and proc.poll() is not None:
            stderr = b""
            try:
                stderr = proc.stderr.read() if proc.stderr else b""
            except Exception:  # noqa: BLE001
                pass
            log.warning("camera %s: ffmpeg exited rc=%s %s", self._camera_id,
                        proc.returncode, stderr.decode(errors="replace").strip()[:300])
            with self._proc_lock:
                self._proc = None
        now = time.monotonic()
        if now >= self._next_start_at:
            self._start_ffmpeg()
            if not self.recording:
                self._next_start_at = now + self._backoff_s
                self._backoff_s = min(self._backoff_s * 2, 60.0)
            else:
                # if it dies instantly the next pass applies backoff
                self._next_start_at = now + self._backoff_s

    # -- watcher -----------------------------------------------------------------

    def _recordings_dir(self) -> str:
        return os.path.join(self._media_root, "recordings", str(self._camera_id))

    def _ensure_date_dirs(self) -> None:
        base = self._recordings_dir()
        now = datetime.now()
        for day in (now, now + timedelta(days=1)):
            try:
                os.makedirs(os.path.join(base, day.strftime("%Y-%m-%d")), exist_ok=True)
            except OSError:
                log.exception("camera %s: cannot create recordings dir", self._camera_id)

    def _scan_segments(self) -> list[FinishedSegment]:
        """All *finished* segments on disk for this camera."""
        results: list[FinishedSegment] = []
        base = self._recordings_dir()
        now = time.time()
        try:
            date_dirs = sorted(d for d in os.listdir(base) if DATE_RE.match(d))
        except OSError:
            return results
        for date_dir in date_dirs:
            dir_path = os.path.join(base, date_dir)
            try:
                names = os.listdir(dir_path)
            except OSError:
                continue
            for name in names:
                path = os.path.join(dir_path, name)
                start = parse_segment_start(path)
                if start is None:
                    continue
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                if (now - stat.st_mtime) < self.FINISHED_AGE_S:
                    continue  # still being written
                results.append(FinishedSegment(
                    path=path, start=start, end=stat.st_mtime, size_bytes=stat.st_size))
        return results

    def _watch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                mode = effective_mode(self._camera)
                self._ensure_date_dirs()
                self._supervise_ffmpeg(mode)
                self._process_segments(mode)
            except Exception:  # noqa: BLE001
                log.exception("camera %s: recorder watcher error", self._camera_id)
            self._stop.wait(self.WATCH_INTERVAL_S)

    def _process_segments(self, current_mode: str) -> None:
        now = time.time()
        with self._windows_lock:
            self._windows = prune_windows(self._windows, now - 3600.0)
            windows = list(self._windows)
        for seg in self._scan_segments():
            if seg.path in self._published:
                continue
            mode_at = effective_mode(
                self._camera, datetime.fromtimestamp(seg.start, tz=timezone.utc))
            if mode_at == "continuous":
                self._publish(seg, kind="continuous")
                self._published.add(seg.path)
            elif mode_at in ("motion", "object"):
                if overlaps_any(seg.start, seg.end, windows):
                    self._publish(seg, kind="event")
                    self._published.add(seg.path)
                elif (now - seg.end) > (self._pre_buffer_s + self.DELETE_GRACE_S):
                    # Old enough that no future event can claim it as pre-buffer.
                    self._delete(seg.path)
            else:  # off
                if (now - seg.end) > self.DELETE_GRACE_S:
                    self._delete(seg.path)
        # Keep the published-set bounded.
        if len(self._published) > 10000:
            existing = {s.path for s in self._scan_segments()}
            self._published &= existing

    def _publish(self, seg: FinishedSegment, kind: str) -> None:
        payload = {
            "camera_id": self._camera_id,
            "path": seg.path,
            "started_at": _utc_iso(seg.start),
            "ended_at": _utc_iso(seg.end),
            "codec": self._camera.get("codec"),
            "size_bytes": seg.size_bytes,
            "kind": kind,
        }
        try:
            self._publish_segment(payload)
        except Exception:  # noqa: BLE001
            log.exception("camera %s: failed to publish segment %s",
                          self._camera_id, seg.path)

    def _delete(self, path: str) -> None:
        try:
            os.remove(path)
            log.debug("camera %s: dropped ring segment %s", self._camera_id, path)
        except OSError:
            pass
