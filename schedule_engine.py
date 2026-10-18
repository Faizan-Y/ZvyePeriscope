"""Pure schedule calculations matching the approved message_schedules schema.

Supported schedule_type values are exactly: ONCE, DAILY, WEEKLY, FORTNIGHTLY,
HOURLY. `joining_date` is Day 1 for journey-based ONCE/FORTNIGHTLY schedules.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

SUPPORTED_SCHEDULE_TYPES = {"ONCE", "DAILY", "WEEKLY", "FORTNIGHTLY", "HOURLY"}


def as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def as_time(value: Any) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    return time.fromisoformat(str(value))


def occurrence_times_on_date(
    schedule: dict[str, Any], member: dict[str, Any], due_date: date
) -> list[datetime]:
    """Return schedule occurrences on `due_date`, using only final-schema fields."""
    schedule_type = str(schedule.get("schedule_type", "DAILY")).upper()
    send_time = as_time(schedule.get("send_time"))

    if schedule_type == "DAILY":
        return [_at(due_date, send_time)] if send_time else []

    if schedule_type == "HOURLY":
        start = as_time(schedule.get("start_time"))
        end = as_time(schedule.get("end_time"))
        interval = schedule.get("interval_minutes")
        if not start or not end or interval is None or int(interval) <= 0 or start > end:
            return []
        cursor = datetime.combine(due_date, start)
        end_dt = datetime.combine(due_date, end)
        result: list[datetime] = []
        while cursor <= end_dt:
            result.append(cursor)
            cursor += timedelta(minutes=int(interval))
        return result

    if schedule_type == "WEEKLY":
        # PostgreSQL convention: Sunday=0, Monday=1, ..., Saturday=6.
        if send_time is None or schedule.get("day_of_week") is None:
            return []
        postgres_dow = (due_date.weekday() + 1) % 7
        return [_at(due_date, send_time)] if postgres_dow == int(schedule["day_of_week"]) else []

    if schedule_type in {"ONCE", "FORTNIGHTLY"}:
        if send_time is None or schedule.get("day_offset") is None:
            return []
        joining_date = as_date(member.get("joining_date"))
        if joining_date is None:
            return []
        first_date = joining_date + timedelta(days=int(schedule["day_offset"]) - 1)
        if schedule_type == "ONCE":
            return [_at(due_date, send_time)] if due_date == first_date else []
        elapsed_days = (due_date - first_date).days
        return (
            [_at(due_date, send_time)]
            if elapsed_days >= 0 and elapsed_days % 14 == 0
            else []
        )

    # Do not invent additional recurrence types: the final SQL CHECK constraint
    # currently permits only the five types listed above.
    return []


def due_occurrences(
    schedule: dict[str, Any],
    member: dict[str, Any],
    now_local: datetime,
    grace_minutes: int,
    catchup_minutes: int = 0,
) -> list[datetime]:
    """Find occurrences in the lookback window and not later than now.

    The lookback is max(grace, catch-up). The grace window covers normal poll
    jitter; the catch-up window (CATCHUP_MINUTES, default 24h in scheduler.py)
    re-picks occurrences missed while the scheduler was down. Live sends are
    deduplicated in message_logs, so occurrences that already went out are
    skipped there. HOURLY schedules catch up only the most recent missed slot:
    back-filling every missed hour would burst many hydration nudges at once.
    """
    now = now_local.replace(second=0, microsecond=0)
    lookback = max(max(0, grace_minutes), max(0, catchup_minutes))
    earliest = now - timedelta(minutes=lookback)
    result: list[datetime] = []
    day = earliest.date()
    while day <= now.date():
        for occurrence in occurrence_times_on_date(schedule, member, day):
            if earliest <= occurrence <= now:
                result.append(occurrence)
        day += timedelta(days=1)
    result = sorted(set(result))
    if str(schedule.get("schedule_type", "DAILY")).upper() == "HOURLY":
        return result[-1:]
    return result


def schedule_matches_member(schedule: dict[str, Any], member: dict[str, Any]) -> bool:
    if not member.get("is_active", False):
        return False
    if member.get("tier_id") is None or schedule.get("tier_id") != member.get("tier_id"):
        return False
    requested_phase = schedule.get("phase_id")
    if requested_phase is not None and member.get("phase_id") != requested_phase:
        return False
    return True


def _at(day: date, clock: time | None) -> datetime:
    if clock is None:
        raise ValueError("A send_time is required for this schedule type")
    return datetime.combine(day, clock.replace(second=0, microsecond=0))
