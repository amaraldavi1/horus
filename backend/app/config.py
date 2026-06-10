"""Application settings loaded from environment variables (CONTRACTS.md §7)."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration. Names match docker-compose / CONTRACTS.md §7."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # When empty, assembled from the POSTGRES_* variables below (or a local
    # SQLite file without them). Assembling it here — instead of string
    # interpolation in docker-compose — keeps passwords with special
    # characters (@ / # %) safe via percent-encoding.
    database_url: str = ""

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "horus"
    postgres_db: str = "horus"
    postgres_password: str | None = None

    @model_validator(mode="after")
    def _default_database_url(self) -> "Settings":
        if not self.database_url:
            if self.postgres_password:
                self.database_url = (
                    f"postgresql+asyncpg://{quote(self.postgres_user, safe='')}:"
                    f"{quote(self.postgres_password, safe='')}"
                    f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
                )
            else:
                self.database_url = "sqlite+aiosqlite:///./horus.db"
        return self
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
