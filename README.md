# Zyvefit outgoing scheduler — aligned to your final SQL

**The SQL schema supplied by you is the source of truth.** This package does not contain a replacement schema, migration, table alteration, or new-column requirement. It uses only these existing tables and columns:

- `tiers`, `phases`, `members`
- `whatsapp_groups`, `group_members`
- `templates`, `message_schedules`, `message_logs`, `incoming_messages`

The scheduler does not read or write `incoming_messages` yet; inbound processing is out of scope.

## Scheduling behavior supported by the final schema

Only the five values allowed by your `message_schedules` constraint are implemented:

- `DAILY`: `send_time`
- `HOURLY`: `start_time`, `end_time`, `interval_minutes`
- `WEEKLY`: `day_of_week` + `send_time` (PostgreSQL convention: Sunday `0`, Saturday `6`)
- `ONCE`: `day_offset` + `send_time`, relative to `members.joining_date` (joining date is Day 1)
- `FORTNIGHTLY`: `day_offset` + `send_time`, repeating every 14 days from that journey-day offset

`phase_id = NULL` on a schedule means any phase in that tier. A non-null `phase_id` only matches members currently in that phase. Members must have `is_active = TRUE` and a matching `tier_id`.

Important schema boundary: the provided schema does not have `plan_start_date`, `plan_end_date`, a `MONTHLY` schedule type, or an expiry-offset field. This code therefore does not invent those fields or recurrences. A Foundation message on the member's Day 1 can be represented as `schedule_type='ONCE', day_offset=1`; a calendar-monthly or plan-anniversary recurrence is not represented by the current constraint and is intentionally left out until you decide how to express it without changing the approved schema.

## Group behavior

The approved schema has no `group_role` or `delivery_mode` columns. Therefore this first outgoing scheduler:

1. Finds active members matching a schedule.
2. Resolves all their active group memberships (`group_members.left_at IS NULL`).
3. Combines matching members into one send per `schedule_id + group_id + scheduled_at` occurrence. This avoids sending two identical messages to a shared couple group when both members match the same rule.
4. Uses the existing `message_logs` fields to record the outgoing send.

Because there is no role column, the scheduler cannot choose a `PRIMARY` versus `FAMILY` group. It treats each current `group_members` relationship as a destination. For the current MVP, keep each member linked only to the group(s) intended to receive that scheduled communication.

## Duplicate protection without changing the schema

The code uses PostgreSQL's transaction-level advisory lock and checks the existing `message_logs` fields (`schedule_id`, `group_id`, `scheduled_at`) before inserting a `PENDING` row. No `idempotency_key` column is required. This is intended for the current single-worker MVP and also serializes concurrent attempts for the same key. If a provider call times out after Periskope may have accepted it, the log is marked `FAILED` and is not automatically retried on the same occurrence; inspect it before retrying.

The approved `message_logs` schema only has `periskope_message_id` for provider identifiers. The code stores the first available message/tracking identifier there; it does not persist a full provider response or separate tracking fields because those columns do not exist.

## Setup

1. Keep your final SQL exactly as supplied. Run that SQL in your development database if you have not already done so. Do not run a different schema from this package.
2. Copy `scheduler.py`, `schedule_engine.py`, `db.py`, `periskope_adapter.py`, and `requirements.txt` alongside your existing `Periskope.py` file. Copy the `tests` folder too.
3. Keep your current `.env` and add the database/config values below. Do not overwrite your Periskope API credentials.

```dotenv
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/YOUR_DATABASE
APP_TIMEZONE=Asia/Kolkata
POLL_SECONDS=30
MISFIRE_GRACE_MINUTES=5
```

4. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

5. Run the tests:

```bash
python -m unittest discover -s tests -v
```

## First test: dry run

```bash
python scheduler.py --once
```

This does not send messages. It prints candidates due now or inside the configured grace window. If no schedule is due, zero candidates is normal.

Preview a particular schedule and member without waiting for the schedule time:

```bash
python scheduler.py --once --force-due-preview --schedule-id 12 --member-code MEMBER_CODE
```

This is still a dry run and previews the combined message for the selected member's group, if other members in that group match the same schedule occurrence.

## Controlled live test

Before a live send, verify that `Periskope.py` exposes the methods expected in `periskope_adapter.py`:

```python
client = Periskope()
client.send_text(chat_id, message)
client.send_media(chat_id, media_url, media_type, caption=message)
```

Then use a real development schedule and member:

```bash
python scheduler.py --send --once --schedule-id 12 --member-code MEMBER_CODE
```

A one-shot live run requires both filters to reduce the chance of sending every due item. Replace demo group chat IDs before any live attempt. Location messages are not implemented in this scheduler slice.

## Continuous mode

After verifying dry run and a controlled live send:

```bash
python scheduler.py
```

This defaults to dry-run. Live sending requires `--send`.
