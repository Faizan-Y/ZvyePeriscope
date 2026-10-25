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


# One cached connection for this single-threaded scheduler. Opening a
# connection per query is cheap over a local socket but costs a full TCP+TLS
# handshake against a managed cloud database (for example DigitalOcean), so
# the helpers below reuse one connection and transparently reconnect after
# network blips. A broken connection rolls back server-side, so retrying a
# unit of work is always safe: either it committed and the next guard query
# sees it, or it never happened.
_shared_connection = None


def _open_shared_connection():
    connection = psycopg.connect(get_database_url(), row_factory=dict_row)
    timezone = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    connection.execute("SELECT set_config('TimeZone', %s, false)", (timezone,))
    connection.commit()
    return connection


def _shared_connection_or_new():
    global _shared_connection
    if _shared_connection is None or _shared_connection.closed:
        _shared_connection = _open_shared_connection()
    return _shared_connection


def _discard_shared_connection():
    global _shared_connection
    if _shared_connection is not None:
        try:
            _shared_connection.close()
        except Exception:
            pass
    _shared_connection = None


def run_with_retry(operation):
    """Run one unit of work inside a transaction on the shared connection.

    Retries once after a lost connection (OperationalError). Any other failure
    rolls the transaction back and propagates, so callers keep their current
    behaviour.
    """
    for attempt in (1, 2):
        conn = None
        try:
            conn = _shared_connection_or_new()
            result = operation(conn)
            conn.commit()
            return result
        except psycopg.OperationalError:
            _discard_shared_connection()
            if attempt == 2:
                raise
        except Exception:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    _discard_shared_connection()
            raise


def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    def operation(conn):
        return list(conn.execute(sql, params).fetchall())

    return run_with_retry(operation)


def fetch_attention_rows() -> list[dict[str, Any]]:
    """Stale scheduler PENDING rows and recent FAILED rows, for the attention report.

    Reads only existing message_logs columns; no schema change. A stale PENDING
    row usually means the process died between logging and sending; a FAILED
    row was attempted once and is not retried automatically.
    """
    sql = """
        SELECT message_log_id, member_id, group_id, schedule_id, template_id,
               status, error_message, scheduled_at, created_at
        FROM message_logs
        WHERE (
                status = 'PENDING'
                AND schedule_id IS NOT NULL
                AND created_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
              )
           OR (
                status = 'FAILED'
                AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
              )
        ORDER BY created_at
        LIMIT 50
    """
    return fetch_all(sql)


def create_pending_log(candidate: dict[str, Any], content: str) -> int | None:
    """Create one log row per schedule + group + recipient + occurrence.

    No idempotency column exists in the approved schema. A PostgreSQL advisory
    transaction lock plus the existing (schedule_id, group_id, member_id,
    scheduled_at) fields prevents duplicate logical sends - one row per
    recipient - from concurrent scheduler workers. The uq_message_logs_send
    unique index enforces the same key at the database level. All work runs
    in one transaction on the shared pooled connection.
    """
    schedule_id = candidate["schedule"]["schedule_id"]
    group_id = candidate["group_id"]
    member_id = candidate.get("log_member_id")
    scheduled_at = candidate["scheduled_at"]
    lock_key = (
        f"zyvefit-send:{schedule_id}:{group_id}:{member_id}:"
        f"{scheduled_at.isoformat(timespec='minutes')}"
    )

    def operation(conn):
        # Transaction-level lock releases automatically when this transaction ends.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
        existing = conn.execute(
            """
            SELECT message_log_id
            FROM message_logs
            WHERE schedule_id = %s
              AND group_id = %s
              AND member_id IS NOT DISTINCT FROM %s
              AND scheduled_at = %s
            ORDER BY message_log_id
            LIMIT 1
            """,
            (schedule_id, group_id, member_id, scheduled_at),
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
                member_id,
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

    return run_with_retry(operation)


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
    def operation(conn):
        conn.execute(
            sql,
            (status, _string_or_none(provider_message_id), error_message, status, message_log_id),
        )

    run_with_retry(operation)


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
