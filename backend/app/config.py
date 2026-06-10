"""Application settings loaded from environment variables (CONTRACTS.md §7)."""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration. Names match docker-compose / CONTRACTS.md §7."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./horus.db"
    redis_url: str = "redis://localhost:6379/0"
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    secret_key: str = "dev-secret-change-me"
    credentials_key: str = Field(default_factory=lambda: Fernet.generate_key().decode())
    internal_api_token: str = "dev-internal-token"
    go2rtc_url: str = "http://localhost:1984"
    media_root: str = "/media"

    admin_email: str | None = None
    admin_password: str | None = None

    # Public (nginx-proxied) path in front of go2rtc, see CONTRACTS.md §3.
    go2rtc_public_path: str = "/go2rtc"

    cors_origins: str = "*"

    access_token_minutes: int = 15
    refresh_token_days: int = 7
    login_max_failures: int = 5
    login_window_seconds: int = 300

    # Optional notification transports (best-effort).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "horus@localhost"
    smtp_starttls: bool = True
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:admin@horus.local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
