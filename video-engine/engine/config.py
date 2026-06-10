"""Environment-driven settings for the video engine (CONTRACTS.md §7)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """All knobs the engine reads from the environment."""

    backend_url: str = field(default_factory=lambda: _env("BACKEND_URL", "http://backend-api:8000"))
    internal_api_token: str = field(default_factory=lambda: _env("INTERNAL_API_TOKEN", ""))
    mqtt_host: str = field(default_factory=lambda: _env("MQTT_HOST", "mosquitto"))
    mqtt_port: int = field(default_factory=lambda: _env_int("MQTT_PORT", 1883))
    media_root: str = field(default_factory=lambda: _env("MEDIA_ROOT", "/media"))
    max_disk_usage_pct: float = field(default_factory=lambda: _env_float("MAX_DISK_USAGE_PCT", 90.0))
    model_path: str = field(default_factory=lambda: _env("MODEL_PATH", "/models/yolov8n.onnx"))
    go2rtc_url: str = field(default_factory=lambda: _env("GO2RTC_URL", "http://go2rtc:1984"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # Tunables (not in the shared contract; sane defaults).
    event_quiet_s: float = field(default_factory=lambda: _env_float("EVENT_QUIET_S", 5.0))
    status_interval_s: float = field(default_factory=lambda: _env_float("STATUS_INTERVAL_S", 10.0))
    retention_interval_s: float = field(default_factory=lambda: _env_float("RETENTION_INTERVAL_S", 300.0))

    @property
    def recordings_dir(self) -> str:
        return os.path.join(self.media_root, "recordings")

    @property
    def events_dir(self) -> str:
        return os.path.join(self.media_root, "events")

    @property
    def snapshots_dir(self) -> str:
        return os.path.join(self.media_root, "snapshots")


def load_settings() -> Settings:
    return Settings()
