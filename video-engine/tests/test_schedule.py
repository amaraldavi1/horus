"""Schedule rule evaluation (pure; CONTRACTS §2 shape, Monday == 0)."""
from __future__ import annotations

from datetime import datetime, timezone

from engine.schedule import active_mode, rule_matches

WEEKDAYS_9_18 = {
    "timezone": "UTC",
    "rules": [{"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "18:00",
               "mode": "continuous"}],
}


def utc(spec: str) -> datetime:
    return datetime.fromisoformat(spec).replace(tzinfo=timezone.utc)


class TestActiveMode:
    def test_inside_window(self) -> None:
        # 2026-06-10 is a Wednesday (weekday 2)
        assert active_mode(WEEKDAYS_9_18, utc("2026-06-10T12:00:00")) == "continuous"

    def test_outside_hours(self) -> None:
        assert active_mode(WEEKDAYS_9_18, utc("2026-06-10T20:00:00")) == "off"

    def test_wrong_day(self) -> None:
        # 2026-06-13 is a Saturday (weekday 5)
        assert active_mode(WEEKDAYS_9_18, utc("2026-06-13T12:00:00")) == "off"

    def test_end_is_exclusive_start_inclusive(self) -> None:
        assert active_mode(WEEKDAYS_9_18, utc("2026-06-10T09:00:00")) == "continuous"
        assert active_mode(WEEKDAYS_9_18, utc("2026-06-10T18:00:00")) == "off"

    def test_timezone_applied(self) -> None:
        schedule = {
            "timezone": "America/Sao_Paulo",  # UTC-3
            "rules": [{"days": [2], "start": "08:00", "end": "18:00", "mode": "motion"}],
        }
        assert active_mode(schedule, utc("2026-06-10T10:00:00")) == "motion"  # 07:00 local? no: 10Z=07:00-3
        # 10:00 UTC == 07:00 local -> before start
        assert active_mode(schedule, utc("2026-06-10T10:59:00")) == "off"
        assert active_mode(schedule, utc("2026-06-10T11:01:00")) == "motion"  # 08:01 local

    def test_overnight_rule_spans_midnight(self) -> None:
        schedule = {
            "timezone": "UTC",
            "rules": [{"days": [4], "start": "22:00", "end": "06:00", "mode": "continuous"}],
        }
        # 2026-06-12 is a Friday (weekday 4)
        assert active_mode(schedule, utc("2026-06-12T23:00:00")) == "continuous"
        assert active_mode(schedule, utc("2026-06-13T05:00:00")) == "continuous"  # Sat morning
        assert active_mode(schedule, utc("2026-06-13T07:00:00")) == "off"
        assert active_mode(schedule, utc("2026-06-12T12:00:00")) == "off"

    def test_no_schedule_or_rules(self) -> None:
        assert active_mode(None, utc("2026-06-10T12:00:00")) == "off"
        assert active_mode({"timezone": "UTC", "rules": []}, utc("2026-06-10T12:00:00")) == "off"

    def test_bad_timezone_falls_back_to_utc(self) -> None:
        schedule = {
            "timezone": "Mars/Olympus",
            "rules": [{"days": [2], "start": "00:00", "end": "23:59", "mode": "motion"}],
        }
        assert active_mode(schedule, utc("2026-06-10T12:00:00")) == "motion"


class TestRuleMatches:
    def test_malformed_rule_never_matches(self) -> None:
        local = datetime(2026, 6, 10, 12, 0)
        assert not rule_matches({"days": [], "start": "09:00", "end": "18:00"}, local)
        assert not rule_matches({"days": [2], "start": "bogus", "end": "18:00"}, local)
        assert not rule_matches({}, local)
