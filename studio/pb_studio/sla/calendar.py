"""SLA due time with optional working hours (phase 8b)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from pb_studio.core.config import Settings
from pb_studio.sla.models import StudioSlaPolicy


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_hhmm(s: str | None) -> time | None:
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mm <= 59:
        return time(h, mm)
    return None


@dataclass(frozen=True)
class _HolidaySet:
    exact_dates: frozenset[date]
    recurring_md: frozenset[tuple[int, int]]


def _parse_holidays(raw: list[Any] | None) -> _HolidaySet:
    exact: set[date] = set()
    rec: set[tuple[int, int]] = set()
    if not raw:
        return _HolidaySet(frozenset(), frozenset())
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            try:
                y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
                exact.add(date(y, mo, d))
            except ValueError:
                continue
        elif len(s) == 5 and s[2] == "-":
            try:
                mo, d = int(s[0:2]), int(s[3:5])
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    rec.add((mo, d))
            except ValueError:
                continue
    return _HolidaySet(frozenset(exact), frozenset(rec))


def _is_holiday(d: date, hs: _HolidaySet) -> bool:
    if d in hs.exact_dates:
        return True
    return (d.month, d.day) in hs.recurring_md


def _working_days_set(policy: StudioSlaPolicy | None) -> frozenset[int]:
    raw = policy.working_days_json if policy and policy.working_days_json is not None else None
    if not raw:
        return frozenset({1, 2, 3, 4, 5})
    out: set[int] = set()
    for x in raw:
        if isinstance(x, int) and 1 <= x <= 7:
            out.add(x)
        elif isinstance(x, str) and x.strip().isdigit():
            v = int(x.strip())
            if 1 <= v <= 7:
                out.add(v)
    return frozenset(out) if out else frozenset({1, 2, 3, 4, 5})


def _policy_tz_name(policy: StudioSlaPolicy | None, settings: Settings) -> str:
    name = (policy.policy_tz if policy else None) or (settings.studio_sla_default_timezone or "UTC")
    name = str(name).strip() or "UTC"
    try:
        ZoneInfo(name)
        return name
    except Exception:
        return "UTC"


def _zone(settings: Settings, policy: StudioSlaPolicy | None) -> ZoneInfo:
    return ZoneInfo(_policy_tz_name(policy, settings))


def _day_window_excl(
    d: date, start_t: time | None, end_t: time | None, tz: ZoneInfo
) -> tuple[datetime, datetime] | None:
    """Returns [inclusive_start, exclusive_end) in tz for that calendar day, or None if no window."""
    if start_t is None and end_t is None:
        day0 = datetime.combine(d, time(0, 0), tzinfo=tz)
        day1 = datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=tz)
        return day0, day1
    st = start_t or time(0, 0)
    if end_t is None:
        day0 = datetime.combine(d, st, tzinfo=tz)
        day1 = datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=tz)
        return day0, day1
    day0 = datetime.combine(d, st, tzinfo=tz)
    day1 = datetime.combine(d, end_t, tzinfo=tz)
    if day1 <= day0:
        return None
    return day0, day1


def _is_working_calendar_day(d: date, days: frozenset[int], hs: _HolidaySet) -> bool:
    if _is_holiday(d, hs):
        return False
    return d.isoweekday() in days


def align_sla_start_local(
    local_dt: datetime,
    *,
    tz: ZoneInfo,
    working_days: frozenset[int],
    hs: _HolidaySet,
    start_t: time | None,
    end_t: time | None,
) -> datetime:
    """First instant >= effective message time when SLA clock may run (in policy local tz)."""
    cur = local_dt
    for _ in range(800):
        d = cur.date()
        if not _is_working_calendar_day(d, working_days, hs):
            nxt = d + timedelta(days=1)
            cur = datetime.combine(nxt, time(0, 0), tzinfo=tz)
            continue
        win = _day_window_excl(d, start_t, end_t, tz)
        if win is None:
            nxt = d + timedelta(days=1)
            cur = datetime.combine(nxt, time(0, 0), tzinfo=tz)
            continue
        w0, w1 = win
        if cur < w0:
            return w0
        if cur >= w1:
            nxt = d + timedelta(days=1)
            cur = datetime.combine(nxt, time(0, 0), tzinfo=tz)
            continue
        return cur
    raise ValueError("align_sla_start_local: too many iterations")


def add_working_minutes_local(
    sla_start_local: datetime,
    minutes: int,
    *,
    tz: ZoneInfo,
    working_days: frozenset[int],
    hs: _HolidaySet,
    start_t: time | None,
    end_t: time | None,
) -> datetime:
    """Add `minutes` of working time starting from sla_start_local (already aligned)."""
    if minutes <= 0:
        return sla_start_local
    remaining = int(minutes)
    cur = sla_start_local
    for _ in range(500_000):
        if remaining <= 0:
            return cur
        d = cur.date()
        if not _is_working_calendar_day(d, working_days, hs):
            nxt = d + timedelta(days=1)
            cur = datetime.combine(nxt, time(0, 0), tzinfo=tz)
            continue
        win = _day_window_excl(d, start_t, end_t, tz)
        if win is None:
            nxt = d + timedelta(days=1)
            cur = datetime.combine(nxt, time(0, 0), tzinfo=tz)
            continue
        w0, w1 = win
        if cur < w0:
            cur = w0
            continue
        if cur >= w1:
            nxt = d + timedelta(days=1)
            cur = datetime.combine(nxt, time(0, 0), tzinfo=tz)
            continue
        seg_end = w1
        avail = int((seg_end - cur).total_seconds() // 60)
        if avail <= 0:
            nxt = d + timedelta(days=1)
            cur = datetime.combine(nxt, time(0, 0), tzinfo=tz)
            continue
        take = min(remaining, avail)
        cur = cur + timedelta(minutes=take)
        remaining -= take
        if remaining <= 0:
            return cur
    raise ValueError("add_working_minutes_local: too many iterations")


def calculate_due_at(
    message_time: datetime,
    policy: StudioSlaPolicy | None,
    settings: Settings,
) -> datetime:
    """UTC due_at for first-response SLA from inbound message time."""
    minutes = _effective_minutes(policy, settings)
    mt_utc = _as_utc(message_time)
    if not settings.studio_sla_working_hours_enabled:
        return mt_utc + timedelta(minutes=minutes)

    tz = _zone(settings, policy)
    hs = _parse_holidays(policy.holidays_json if policy and policy.holidays_json else None)
    days = _working_days_set(policy)
    start_t = _parse_hhmm(policy.working_hours_start if policy else None)
    end_t = _parse_hhmm(policy.working_hours_end if policy else None)

    local = mt_utc.astimezone(tz)
    sla_start = align_sla_start_local(
        local,
        tz=tz,
        working_days=days,
        hs=hs,
        start_t=start_t,
        end_t=end_t,
    )
    due_local = add_working_minutes_local(
        sla_start,
        minutes,
        tz=tz,
        working_days=days,
        hs=hs,
        start_t=start_t,
        end_t=end_t,
    )
    return _as_utc(due_local)


def _effective_minutes(policy: StudioSlaPolicy | None, settings: Settings) -> int:
    if policy is not None:
        return max(1, int(policy.first_response_minutes))
    return max(1, int(settings.studio_sla_default_first_response_minutes))


def policy_blocks_new_incidents(policy: StudioSlaPolicy | None, now: datetime) -> bool:
    if policy is None:
        return False
    now_u = _as_utc(now)
    if policy.is_muted:
        return True
    mu = policy.muted_until
    if mu is not None and now_u < _as_utc(mu):
        return True
    return False
