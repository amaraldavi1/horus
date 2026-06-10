# Horus video-engine

Camera ingestion service of the Horus VMS. No web framework: it talks MQTT to
the backend, runs one ffmpeg remux per camera and an OpenCV detection loop.
Contracts (topics, payloads, disk layout, env vars) live in
[`docs/CONTRACTS.md`](../docs/CONTRACTS.md) — that document wins on conflict.

## Architecture

```
engine/main.py ── Engine
  ├─ hardware.py      probe NVDEC/VAAPI/QSV + TensorRT/EdgeTPU/OpenVINO/ONNX-CPU
  │                   → retained report on horus/engine/hardware (§1.3)
  ├─ mqtt.py          paho-mqtt v2 wrapper (retrying connect, JSON pub/sub)
  ├─ GET /internal/cameras (X-Internal-Token, retry/backoff)   (§2)
  ├─ one CameraWorker per enabled camera (threads; ffmpeg subprocesses
  │                   do the heavy lifting)
  ├─ horus/engine/command subscriber: reload_cameras / reload_zones /
  │                   restart_camera (§1.4)
  └─ retention.py     5-min loop: age-based deletion + disk-pressure rotation

worker.py ── CameraWorker (per camera)
  ├─ detection stream: cv2.VideoCapture(sub_url, fallback main_url, FFMPEG
  │     backend, RTSP-over-TCP + hwaccel via OPENCV_FFMPEG_CAPTURE_OPTIONS),
  │     sampled at detect_fps, downscaled to 640px
  ├─ motion.py        MOG2 background subtraction gated by zone masks
  │     (normalized polygons; includes OR'd, excludes subtracted, no include
  │     = full frame), sensitivity → threshold, min_area fraction, dwell_ms
  ├─ objects.py       optional ONNX YOLO (MODEL_PATH); letterbox → NMS →
  │     person/car/animal mapping; missing model = log once, motion-only;
  │     ORT providers chosen from the hardware report
  ├─ events.py        lifecycle: sustained motion → phase=start + WebP
  │     snapshot; object hits → phase=update; 5s quiet → phase=end with
  │     concat'd clip (§1.1) under /media/events/...
  ├─ recorder.py      ffmpeg `-c copy -f segment` into
  │     /media/recordings/{cid}/{YYYY-MM-DD}/{HH-MM-SS}.mp4; watcher thread
  │     publishes finished segments on horus/recordings/{cid} (§1.5, HTTP
  │     POST /internal/recordings fallback)
  └─ status: retained horus/status/{cid} (§1.2), throttled 10s + on change,
        exponential reconnect backoff
```

### Recording modes (per camera, `recording_mode`)

* **continuous** — every segment kept + published (`kind=continuous`).
* **motion / object** — the segmenter still runs 24/7 into a small ring;
  only segments overlapping an event window (`started_at − pre_buffer_s` →
  `ended_at`) are kept and published (`kind=event`), the rest are deleted by
  the watcher. This implements the pre-event buffer **without re-encoding**.
  The event clip itself is assembled from those segments with the ffmpeg
  concat demuxer (`-c copy`).
* **scheduled** — `schedule.py` evaluates the rules (days Monday=0,
  HH:MM in the schedule's timezone, overnight ranges supported) to pick the
  effective mode per segment; outside all rules = off.
* **off** — no ffmpeg process at all (detection/events still run).

### Retention (`retention.py`)

Every 5 minutes: delete continuous recordings older than
`retention_days_continuous` and event clips/snapshots older than
`retention_days_event` (per camera); if `MEDIA_ROOT` usage ≥
`MAX_DISK_USAGE_PCT`, delete the **oldest continuous** segments first until
~5% below the threshold; prune empty date directories. All deletions logged.

### Failure tolerance

Every external interaction (ffmpeg, MQTT, backend HTTP, camera streams,
hardware probes) is wrapped: one bad camera reconnects with exponential
backoff and never takes the process down. SIGTERM stops workers, terminates
ffmpeg children and disconnects MQTT cleanly.

## Environment

`BACKEND_URL`, `INTERNAL_API_TOKEN`, `MQTT_HOST`/`MQTT_PORT`, `MEDIA_ROOT`,
`MAX_DISK_USAGE_PCT`, `MODEL_PATH` (default `/models/yolov8n.onnx`),
`GO2RTC_URL`, plus optional `LOG_LEVEL`, `EVENT_QUIET_S`,
`STATUS_INTERVAL_S`, `RETENTION_INTERVAL_S`. See `engine/config.py`.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m compileall engine          # syntax check
pytest tests/                        # pure-logic tests (no camera needed)
python -m engine.main                # needs MQTT + backend (docker-compose)
```

Object detection model: see [`models/README.md`](models/README.md).
