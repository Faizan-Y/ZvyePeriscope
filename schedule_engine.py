"""Pure schedule calculations matching the approved message_schedules schema.

Supported schedule_type values are exactly: ONCE, DAILY, WEEKLY, FORTNIGHTLY,
HOURLY. `joining_date` is Day 1 for journey-based ONCE/FORTNIGHTLY schedules.

`due_occurrences` accepts an aware member-local datetime and returns aware UTC
instants. Local wall-clock occurrences that do not exist because of a DST jump
are skipped. Ambiguous wall-clock occurrences during a DST fall-back use the
first occurrence (fold=0), so a scheduled wall time is never emitted twice.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

SUPPORTED_SCHEDULE_TYPES = {"ONCE", "DAILY", "WEEKLY", "FORTNIGHTLY", "HOURLY"}
UTC = timezone.utc


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
    """Return naive local wall-clock occurrences on `due_date`."""
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


def _resolve_local_occurrence(local_occurrence: datetime, member_tz) -> datetime | None:
    """Resolve a naive local wall time to one UTC instant.

    A round-trip through UTC distinguishes valid wall times from nonexistent
    ones. During a fall-back overlap, both folds round-trip; choosing the
    earliest UTC instant (fold=0 for normal ZoneInfo transitions) sends once at
    the first occurrence of that wall-clock time.
    """
    if local_occurrence.tzinfo is not None:
        raise ValueError("Local schedule occurrence must be a naive wall-clock datetime")

    valid_instants: set[datetime] = set()
    for fold in (0, 1):
        local_aware = local_occurrence.replace(tzinfo=member_tz, fold=fold)
        utc_instant = local_aware.astimezone(UTC)
        round_trip = utc_instant.astimezone(member_tz)
        if round_trip.replace(tzinfo=None) == local_occurrence:
            valid_instants.add(utc_instant)

    if not valid_instants:
        # DST spring-forward gap: this local wall time never occurred.
        return None

    # Normal times produce one unique instant. Ambiguous times produce two;
    # choose the first one so the same wall-clock schedule does not fire twice.
    return min(valid_instants)


def due_occurrences(
    schedule: dict[str, Any],
    member: dict[str, Any],
    now_local: datetime,
    grace_minutes: int,
    catchup_minutes: int = 0,
) -> list[datetime]:
    """Return due schedule occurrences as timezone-aware UTC instants.

    The lookback is measured as elapsed time in UTC, not wall-clock time, so
    grace/catch-up windows remain correct across daylight-saving transitions.
    HOURLY schedules catch up only the most recent missed slot to avoid bursts.
    `now_local` must be timezone-aware and use the member's IANA timezone.
    """
    if now_local.tzinfo is None or now_local.utcoffset() is None:
        raise ValueError("now_local must be timezone-aware and use the member's timezone")

    member_tz = now_local.tzinfo
    now_utc = now_local.astimezone(UTC).replace(second=0, microsecond=0)
    lookback = max(max(0, grace_minutes), max(0, catchup_minutes))
    earliest_utc = now_utc - timedelta(minutes=lookback)

    # Determine the date range in the member's local calendar. UTC is used for
    # elapsed-window comparisons; local dates are used for recurrence rules.
    first_local_date = earliest_utc.astimezone(member_tz).date()
    last_local_date = now_utc.astimezone(member_tz).date()

    result: list[datetime] = []
    day = first_local_date
    while day <= last_local_date:
        for local_occurrence in occurrence_times_on_date(schedule, member, day):
            occurrence_utc = _resolve_local_occurrence(local_occurrence, member_tz)
            if occurrence_utc is not None and earliest_utc <= occurrence_utc <= now_utc:
                result.append(occurrence_utc)
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
