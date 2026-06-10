"""Pure schedule evaluation (recording_mode == "scheduled").

Rules (CONTRACTS §2): ``{"days": [0..6], "start": "HH:MM", "end": "HH:MM",
"mode": "..."}`` with Monday == 0, evaluated in the schedule's timezone.
Overnight ranges (start > end) span midnight. No matching rule => "off".
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger("engine.schedule")

DEFAULT_MODE = "off"


def _parse_hhmm(value: str) -> time | None:
    try:
        hours, minutes = value.strip().split(":")
        return time(int(hours), int(minutes))
    except Exception:  # noqa: BLE001
        return None


def rule_matches(rule: dict[str, Any], local_dt: datetime) -> bool:
    """Does this rule cover the given *local* datetime?

    For overnight rules (start > end), the rule's ``days`` refer to the day
    the window *starts* on; e.g. days=[4], 22:00-06:00 covers Friday night
    into Saturday morning.
    """
    start = _parse_hhmm(str(rule.get("start", "")))
    end = _parse_hhmm(str(rule.get("end", "")))
    days = rule.get("days") or []
    if start is None or end is None or not days:
        return False
    weekday = local_dt.weekday()  # Monday == 0, matching the contract
    now_t = local_dt.time()
    if start <= end:  # same-day window
        return weekday in days and start <= now_t < end
    # overnight window: today after start, or "yesterday's" rule before end
    if weekday in days and now_t >= start:
        return True
    prev_day = (weekday - 1) % 7
    return prev_day in days and now_t < end


def active_mode(schedule: dict[str, Any] | None, now_utc: datetime | None = None) -> str:
    """Resolve the effective recording mode for a scheduled camera.

    Returns one of the rule modes ("continuous" | "motion" | "object" | "off")
    or DEFAULT_MODE when nothing matches / schedule is malformed.
    """
    if not schedule or not schedule.get("rules"):
        return DEFAULT_MODE
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    tz_name = schedule.get("timezone") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 - bad tz from config must not crash
        log.warning("Unknown timezone %r in schedule; falling back to UTC", tz_name)
        tz = timezone.utc  # type: ignore[assignment]
    local_dt = now_utc.astimezone(tz)
    for rule in schedule["rules"]:
        try:
            if rule_matches(rule, local_dt):
                return str(rule.get("mode", DEFAULT_MODE))
        except Exception:  # noqa: BLE001
            continue
    return DEFAULT_MODE
