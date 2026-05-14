from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pb_studio.core.config import Settings
from pb_studio.sla.calendar import calculate_due_at, policy_blocks_new_incidents
from pb_studio.sla.models import StudioSlaPolicy


def _s(
    *,
    wh: bool = False,
    default_tz: str = "UTC",
) -> Settings:
    return Settings(
        studio_sla_working_hours_enabled=wh,
        studio_sla_default_timezone=default_tz,
        studio_sla_default_first_response_minutes=60,
    )


def _pol(**kwargs) -> StudioSlaPolicy:
    base = dict(
        chat_role="client_chat",
        first_response_minutes=60,
        followup_minutes=None,
        is_active=True,
        policy_tz="UTC",
        working_days_json=[1, 2, 3, 4, 5],
        working_hours_start="10:00",
        working_hours_end="18:00",
        holidays_json=None,
        is_muted=False,
        muted_until=None,
        mute_reason=None,
    )
    base.update(kwargs)
    return StudioSlaPolicy(**base)


def test_wh_disabled_same_as_simple_add():
    s = _s(wh=False)
    pol = _pol()
    mt = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    due = calculate_due_at(mt, pol, s)
    assert due == mt.replace(tzinfo=timezone.utc) + timedelta(minutes=60)


def test_wh_enabled_in_window_adds_minutes():
    s = _s(wh=True)
    pol = _pol()
    mt = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)  # Monday
    due = calculate_due_at(mt, pol, s)
    assert due == datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)


def test_wh_enabled_after_hours_moves_to_next_day():
    s = _s(wh=True)
    pol = _pol()
    mt = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)  # Monday after 18:00
    due = calculate_due_at(mt, pol, s)
    assert due == datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc)  # Tue 10:00 + 60m


def test_wh_weekend_moves_to_monday():
    s = _s(wh=True)
    pol = _pol()
    mt = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)  # Saturday
    due = calculate_due_at(mt, pol, s)
    assert due == datetime(2026, 6, 8, 11, 0, tzinfo=timezone.utc)  # Mon 10:00 + 60m


def test_holiday_skips_day():
    s = _s(wh=True)
    pol = _pol(holidays_json=["2026-06-01"])
    mt = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)  # Monday holiday
    due = calculate_due_at(mt, pol, s)
    assert due == datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc)  # Tue 10:00 + 60m


def test_policy_blocks_is_muted():
    pol = _pol(is_muted=True)
    assert policy_blocks_new_incidents(pol, datetime(2026, 1, 1, tzinfo=timezone.utc)) is True


def test_policy_blocks_muted_until_future():
    pol = _pol(
        is_muted=False,
        muted_until=datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert policy_blocks_new_incidents(pol, datetime(2026, 1, 1, tzinfo=timezone.utc)) is True


def test_policy_allows_after_muted_until():
    pol = _pol(
        is_muted=False,
        muted_until=datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert policy_blocks_new_incidents(pol, datetime(2026, 1, 1, tzinfo=timezone.utc)) is False


def test_cross_end_of_day_window():
    s = _s(wh=True)
    pol = _pol(first_response_minutes=120, working_hours_start="10:00", working_hours_end="18:00")
    mt = datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)  # Monday 17:00, 60m left in window
    due = calculate_due_at(mt, pol, s)
    assert due == datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc)  # 60m Mon + 60m Tue from 10:00
