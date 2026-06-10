"""Initial schema: all Horus backend tables (mirrors app/models.py).

Revision ID: 0001
Revises:
Create Date: 2026-06-10

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _enum(name: str, *values: str) -> sa.Enum:
    # Matches app.models._enum: stored as VARCHAR(16), no native PG enum type.
    return sa.Enum(*values, name=name, native_enum=False, length=16)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", _enum("user_role", "admin", "operator", "viewer"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("manufacturer", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column(
            "protocol",
            _enum("camera_protocol", "rtsp", "onvif", "rtmp", "http", "usb"),
            nullable=False,
        ),
        sa.Column("main_url_encrypted", sa.String(length=1024), nullable=True),
        sa.Column("sub_url_encrypted", sa.String(length=1024), nullable=True),
        sa.Column("username_encrypted", sa.String(length=512), nullable=True),
        sa.Column("password_encrypted", sa.String(length=512), nullable=True),
        sa.Column("codec", sa.String(length=16), nullable=True),
        sa.Column("ptz", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "recording_mode",
            _enum("recording_mode", "off", "continuous", "scheduled", "motion", "object"),
            nullable=False,
        ),
        sa.Column("pre_buffer_s", sa.Integer(), nullable=False),
        sa.Column("segment_s", sa.Integer(), nullable=False),
        sa.Column("retention_days_continuous", sa.Integer(), nullable=False),
        sa.Column("retention_days_event", sa.Integer(), nullable=False),
        sa.Column("detect_objects", sa.Boolean(), nullable=False),
        sa.Column("detect_fps", sa.Integer(), nullable=False),
        sa.Column("storage_target", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "camera_permissions",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "camera_id",
            sa.Integer(),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "camera_id",
            sa.Integer(),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", _enum("zone_kind", "include", "exclude"), nullable=False),
        sa.Column("polygon", sa.JSON(), nullable=False),
        sa.Column("sensitivity", sa.Integer(), nullable=False),
        sa.Column("min_area", sa.Float(), nullable=False),
        sa.Column("dwell_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_zones_camera_id", "zones", ["camera_id"])

    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "camera_id",
            sa.Integer(),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("codec", sa.String(length=16), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("kind", _enum("recording_kind", "continuous", "event"), nullable=False),
    )
    op.create_index("ix_recordings_camera_started", "recordings", ["camera_id", "started_at"])

    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "camera_id",
            sa.Integer(),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", _enum("event_type", "motion", "object"), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "zone_id",
            sa.Integer(),
            sa.ForeignKey("zones.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("snapshot_path", sa.String(length=512), nullable=True),
        sa.Column("clip_path", sa.String(length=512), nullable=True),
        sa.Column(
            "recording_id",
            sa.Integer(),
            sa.ForeignKey("recordings.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_events_camera_started", "events", ["camera_id", "started_at"])

    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "camera_id",
            sa.Integer(),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel",
            _enum("notification_channel", "push", "email", "webhook"),
            nullable=False,
        ),
        sa.Column("target", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subscription", sa.JSON(), nullable=False),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_table("push_subscriptions")
    op.drop_table("audit_log")
    op.drop_table("notifications")
    op.drop_table("schedules")
    op.drop_table("events")
    op.drop_table("recordings")
    op.drop_table("zones")
    op.drop_table("camera_permissions")
    op.drop_table("cameras")
    op.drop_table("users")
