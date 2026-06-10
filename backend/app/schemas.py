"""Pydantic request/response schemas (public API shapes per CONTRACTS.md §4)."""
from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import (
    CameraProtocol,
    EventType,
    NotificationChannel,
    RecordingKind,
    RecordingMode,
    UserRole,
    ZoneKind,
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


# --- Auth / users -----------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime
    camera_ids: list[int] = []


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8)
    role: UserRole = UserRole.viewer
    is_active: bool = True
    camera_ids: list[int] = []


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8)
    role: UserRole | None = None
    is_active: bool | None = None
    camera_ids: list[int] | None = None


# --- Cameras ----------------------------------------------------------------


class CameraBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    manufacturer: str | None = None
    model: str | None = None
    protocol: CameraProtocol = CameraProtocol.rtsp
    codec: str | None = None
    ptz: bool = False
    enabled: bool = True
    recording_mode: RecordingMode = RecordingMode.motion
    pre_buffer_s: int = Field(default=5, ge=0, le=60)
    segment_s: int = Field(default=30, ge=5, le=3600)
    retention_days_continuous: int = Field(default=7, ge=0)
    retention_days_event: int = Field(default=30, ge=0)
    detect_objects: bool = False
    detect_fps: int = Field(default=5, ge=1, le=30)
    storage_target: str = "local"


class CameraCreate(CameraBase):
    main_url: str = Field(min_length=1)
    sub_url: str | None = None
    username: str | None = None
    password: str | None = None


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    manufacturer: str | None = None
    model: str | None = None
    protocol: CameraProtocol | None = None
    main_url: str | None = None
    sub_url: str | None = None
    username: str | None = None
    password: str | None = None
    codec: str | None = None
    ptz: bool | None = None
    enabled: bool | None = None
    recording_mode: RecordingMode | None = None
    pre_buffer_s: int | None = Field(default=None, ge=0, le=60)
    segment_s: int | None = Field(default=None, ge=5, le=3600)
    retention_days_continuous: int | None = Field(default=None, ge=0)
    retention_days_event: int | None = Field(default=None, ge=0)
    detect_objects: bool | None = None
    detect_fps: int | None = Field(default=None, ge=1, le=30)
    storage_target: str | None = None


class CameraOut(CameraBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    main_url: str | None = None  # masked, credentials stripped
    sub_url: str | None = None  # masked, credentials stripped
    created_at: datetime


class CameraTestRequest(BaseModel):
    url: str
    protocol: CameraProtocol = CameraProtocol.rtsp


class CameraTestResult(BaseModel):
    ok: bool
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None


class DiscoveredCamera(BaseModel):
    ip: str
    name: str | None = None
    xaddr: str
    manufacturer: str | None = None


class PTZRequest(BaseModel):
    action: Literal["move", "stop", "preset"]
    pan: float = Field(default=0.0, ge=-1.0, le=1.0)
    tilt: float = Field(default=0.0, ge=-1.0, le=1.0)
    zoom: float = Field(default=0.0, ge=-1.0, le=1.0)
    preset: str | None = None


class StreamUrls(BaseModel):
    webrtc_url: str
    hls_url: str
    sub_webrtc_url: str | None = None
    sub_hls_url: str | None = None


# --- Zones / schedules ------------------------------------------------------


class ZoneBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ZoneKind = ZoneKind.include
    polygon: list[list[float]]
    sensitivity: int = Field(default=25, ge=1, le=100)
    min_area: float = Field(default=0.005, ge=0.0, le=1.0)
    dwell_ms: int = Field(default=500, ge=0)

    @field_validator("polygon")
    @classmethod
    def _validate_polygon(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 3:
            raise ValueError("polygon must have at least 3 points")
        for point in v:
            if len(point) != 2 or not all(0.0 <= c <= 1.0 for c in point):
                raise ValueError("polygon points must be [x, y] pairs normalized to 0..1")
        return v


class ZoneCreate(ZoneBase):
    pass


class ZoneOut(ZoneBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int


class ScheduleRule(BaseModel):
    days: list[int] = Field(min_length=1)
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")
    mode: RecordingMode

    @field_validator("days")
    @classmethod
    def _validate_days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("days must be 0..6 (Monday=0)")
        return v


class ScheduleUpdate(BaseModel):
    timezone: str = "UTC"
    rules: list[ScheduleRule] = []


class ScheduleOut(ScheduleUpdate):
    model_config = ConfigDict(from_attributes=True)

    camera_id: int


# --- Recordings / events ----------------------------------------------------


class RecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    path: str
    started_at: datetime
    ended_at: datetime | None
    codec: str | None
    size_bytes: int
    kind: RecordingKind


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    camera_id: int
    type: EventType
    label: str | None
    confidence: float | None
    zone_id: int | None
    started_at: datetime
    ended_at: datetime | None
    duration_s: float | None
    snapshot_path: str | None
    clip_path: str | None
    recording_id: int | None


# --- Notifications ----------------------------------------------------------


class NotificationCreate(BaseModel):
    channel: NotificationChannel
    target: str = Field(min_length=1, max_length=512)
    enabled: bool = True
    filters: dict = {}


class NotificationUpdate(BaseModel):
    channel: NotificationChannel | None = None
    target: str | None = Field(default=None, min_length=1, max_length=512)
    enabled: bool | None = None
    filters: dict | None = None


class NotificationOut(NotificationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class PushSubscribeRequest(BaseModel):
    subscription: dict


# --- System / audit ---------------------------------------------------------


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    action: str
    target: str | None
    ip: str | None
    created_at: datetime
