"""Small shared helpers: URL masking/credential injection, media paths, timestamps."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import HTTPException, status

from app.config import get_settings


def mask_url(url: str | None) -> str | None:
    """Strip userinfo credentials from a URL for public API responses."""
    if not url:
        return url
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit((parts.scheme, f"***:***@{host}", parts.path, parts.query, parts.fragment))


def with_credentials(url: str | None, username: str | None, password: str | None) -> str | None:
    """Inject username/password into a URL that has no userinfo (internal API)."""
    if not url or not username:
        return url
    parts = urlsplit(url)
    if "@" in parts.netloc:
        return url  # URL already carries credentials
    userinfo = quote(username, safe="")
    if password:
        userinfo += f":{quote(password, safe='')}"
    return urlunsplit((parts.scheme, f"{userinfo}@{parts.netloc}", parts.path, parts.query, parts.fragment))


def resolve_media_path(raw_path: str | None) -> Path:
    """Resolve a stored media path, ensuring it stays inside MEDIA_ROOT."""
    if not raw_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not available")
    media_root = Path(get_settings().media_root).resolve()
    path = Path(raw_path)
    if not path.is_absolute():
        path = media_root / path
    path = path.resolve()
    if not path.is_relative_to(media_root):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Path outside media root")
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    return path


def parse_ts(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp ('Z' suffix supported); naive values are assumed UTC."""
    if value is None:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
