"""SQLAlchemy 2.0 models for the Horus backend."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class CameraProtocol(str, enum.Enum):
    rtsp = "rtsp"
    onvif = "onvif"
    rtmp = "rtmp"
    http = "http"
    usb = "usb"


class RecordingMode(str, enum.Enum):
    off = "off"
    continuous = "continuous"
    scheduled = "scheduled"
    motion = "motion"
    object = "object"


class ZoneKind(str, enum.Enum):
    include = "include"
    exclude = "exclude"


class RecordingKind(str, enum.Enum):
    continuous = "continuous"
    event = "event"


class EventType(str, enum.Enum):
    motion = "motion"
    object = "object"


class NotificationChannel(str, enum.Enum):
    push = "push"
    email = "email"
    webhook = "webhook"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, native_enum=False, length=16, values_callable=lambda x: [m.value for m in x])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"), default=UserRole.viewer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    camera_permissions: Mapped[list[CameraPermission]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    manufacturer: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    protocol: Mapped[CameraProtocol] = mapped_column(_enum(CameraProtocol, "camera_protocol"), default=CameraProtocol.rtsp)
    main_url_encrypted: Mapped[str | None] = mapped_column(String(1024))
    sub_url_encrypted: Mapped[str | None] = mapped_column(String(1024))
    username_encrypted: Mapped[str | None] = mapped_column(String(512))
    password_encrypted: Mapped[str | None] = mapped_column(String(512))
    codec: Mapped[str | None] = mapped_column(String(16))
    ptz: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    recording_mode: Mapped[RecordingMode] = mapped_column(_enum(RecordingMode, "recording_mode"), default=RecordingMode.motion)
    pre_buffer_s: Mapped[int] = mapped_column(Integer, default=5)
    segment_s: Mapped[int] = mapped_column(Integer, default=30)
    retention_days_continuous: Mapped[int] = mapped_column(Integer, default=7)
    retention_days_event: Mapped[int] = mapped_column(Integer, default=30)
    detect_objects: Mapped[bool] = mapped_column(Boolean, default=False)
    detect_fps: Mapped[int] = mapped_column(Integer, default=5)
    storage_target: Mapped[str] = mapped_column(String(64), default="local")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    zones: Mapped[list[Zone]] = relationship(back_populates="camera", cascade="all, delete-orphan")
    schedule: Mapped[Schedule | None] = relationship(back_populates="camera", cascade="all, delete-orphan", uselist=False)


class CameraPermission(Base):
    __tablename__ = "camera_permissions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True)

    user: Mapped[User] = relationship(back_populates="camera_permissions")


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[ZoneKind] = mapped_column(_enum(ZoneKind, "zone_kind"), default=ZoneKind.include)
    polygon: Mapped[list] = mapped_column(JSON, default=list)
    sensitivity: Mapped[int] = mapped_column(Integer, default=25)
    min_area: Mapped[float] = mapped_column(Float, default=0.005)
    dwell_ms: Mapped[int] = mapped_column(Integer, default=500)

    camera: Mapped[Camera] = relationship(back_populates="zones")


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (Index("ix_recordings_camera_started", "camera_id", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(512))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    codec: Mapped[str | None] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    kind: Mapped[RecordingKind] = mapped_column(_enum(RecordingKind, "recording_kind"), default=RecordingKind.continuous)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_camera_started", "camera_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    type: Mapped[EventType] = mapped_column(_enum(EventType, "event_type"))
    label: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float | None] = mapped_column(Float)
    snapshot_path: Mapped[str | None] = mapped_column(String(512))
    clip_path: Mapped[str | None] = mapped_column(String(512))
    recording_id: Mapped[int | None] = mapped_column(ForeignKey("recordings.id", ondelete="SET NULL"))


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), unique=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    rules: Mapped[list] = mapped_column(JSON, default=list)

    camera: Mapped[Camera] = relationship(back_populates="schedule")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[NotificationChannel] = mapped_column(_enum(NotificationChannel, "notification_channel"))
    target: Mapped[str] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subscription: Mapped[dict] = mapped_column(JSON)
