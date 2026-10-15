"""PostgreSQL helpers using only columns in the user's final schema."""
from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is missing. Add it to your existing .env file.")
    return url


def connect_database(*, dict_rows: bool = False):
    row_factory = dict_row if dict_rows else None
    conn = psycopg.connect(get_database_url(), row_factory=row_factory)
    timezone = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    conn.execute("SELECT set_config('TimeZone', %s, false)", (timezone,))
    conn.commit()
    return conn


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect_database(dict_rows=True) as conn:
        return list(conn.execute(sql, params).fetchall())


def create_pending_log(candidate: dict[str, Any], content: str) -> int | None:
    """Create one log row per schedule + group + scheduled occurrence.

    No idempotency column exists in the approved schema. A PostgreSQL advisory
    transaction lock plus the existing (schedule_id, group_id, scheduled_at)
    fields prevents duplicate logical sends from concurrent scheduler workers.
    This does not alter the database schema.
    """
    schedule_id = candidate["schedule"]["schedule_id"]
    group_id = candidate["group_id"]
    scheduled_at = candidate["scheduled_at"]
    lock_key = f"zyvefit-send:{schedule_id}:{group_id}:{scheduled_at.isoformat(timespec='minutes')}"

    with connect_database(dict_rows=True) as conn:
        # Transaction-level lock releases automatically when this transaction ends.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
        existing = conn.execute(
            """
            SELECT message_log_id
            FROM message_logs
            WHERE schedule_id = %s
              AND group_id = %s
              AND scheduled_at = %s
            ORDER BY message_log_id
            LIMIT 1
            """,
            (schedule_id, group_id, scheduled_at),
        ).fetchone()
        if existing:
            return None

        row = conn.execute(
            """
            INSERT INTO message_logs (
                member_id,
                group_id,
                schedule_id,
                template_id,
                message_type,
                message_content,
                media_url,
                status,
                scheduled_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', %s)
            RETURNING message_log_id
            """,
            (
                candidate.get("log_member_id"),
                group_id,
                schedule_id,
                candidate["schedule"]["template_id"],
                candidate["schedule"]["message_type"],
                content,
                candidate["schedule"].get("media_url"),
                scheduled_at,
            ),
        ).fetchone()
        return row["message_log_id"] if row else None


def update_log_after_send(
    message_log_id: int,
    status: str,
    provider_response: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    """Persist only provider information supported by message_logs columns."""
    payload = provider_response or {}
    provider_message_id = _first(
        payload, "message_id", "messageId", "id", "unique_id", "uniqueId", "track_by", "trackBy"
    )
    if provider_message_id is None and payload:
        # If a provider failure response contains no ID, retain a compact response
        # in error_message without introducing a provider_response column.
        if status == "FAILED" and not error_message:
            error_message = str(payload)[:4000]

    sql = """
        UPDATE message_logs
        SET status = %s,
            periskope_message_id = %s,
            error_message = %s,
            sent_at = CASE
                WHEN %s IN ('SENT', 'DELIVERED', 'READ')
                THEN CURRENT_TIMESTAMP
                ELSE sent_at
            END
        WHERE message_log_id = %s
    """
    with connect_database() as conn:
        conn.execute(
            sql,
            (status, _string_or_none(provider_message_id), error_message, status, message_log_id),
        )


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        return str(value)
    return str(value)
