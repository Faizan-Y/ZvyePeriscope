"""
Default mode is dry-run. Use --send only after checking the preview and the
"""
from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import sys
import time as time_module
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from db import create_pending_log, fetch_all, fetch_attention_rows, get_database_url, update_log_after_send
from periskope_adapter import build_client, send_message
from schedule_engine import due_occurrences, schedule_matches_member
from pathlib import Path

logger = logging.getLogger(__name__)

# Catch-up is a startup recovery pass: the first completed cycle re-picks
# occurrences missed while the scheduler was down. See run_one_cycle.
_catchup_pending = True

# Occurrences already processed by this process run, keyed identically to the
# message_logs dedup key (schedule + group + member + time). Later cycles skip
# them without another database round-trip; the DB check stays authoritative
# for restarts and concurrent processes. See run_one_cycle.
_attempted_candidates: set[tuple[Any, ...]] = set()

# Consecutive heartbeat ping failures, for state-change logging only. The
# dead-man-switch service (HEARTBEAT_URL) alerts when pings stop arriving.
_heartbeat_failures = 0

SCHEDULES_SQL = """
    SELECT
        ms.*,
        t.tier_name,
        tp.template_code,
        tp.template_name,
        tp.message_type,
        tp.message_content,
        tp.media_url,
        tp.language
    FROM message_schedules ms
    JOIN tiers t ON t.tier_id = ms.tier_id
    JOIN templates tp ON tp.template_id = ms.template_id
    WHERE ms.is_active = TRUE
    ORDER BY ms.schedule_id
"""

MEMBERS_SQL = """
    SELECT
        m.*,
        t.tier_name,
        ph.phase_name
    FROM members m
    LEFT JOIN tiers t ON t.tier_id = m.tier_id
    LEFT JOIN phases ph ON ph.phase_id = m.phase_id
    WHERE m.is_active = TRUE
      AND m.tier_id IS NOT NULL
    ORDER BY m.member_id
"""

DESTINATIONS_SQL = """
    SELECT
        gm.member_id,
        wg.group_id,
        wg.group_name,
        wg.periskope_chat_id
    FROM group_members gm
    JOIN whatsapp_groups wg ON wg.group_id = gm.group_id
    WHERE gm.left_at IS NULL
    ORDER BY gm.member_id, wg.group_id
"""


def load_configuration() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    return fetch_all(SCHEDULES_SQL), fetch_all(MEMBERS_SQL), fetch_all(DESTINATIONS_SQL)


def build_candidates(
    schedules: list[dict[str, Any]],
    members: list[dict[str, Any]],
    destinations: list[dict[str, Any]],
    now_local: datetime,
    grace_minutes: int,
    force_due_for_preview: bool = False,
    catchup_minutes: int = 0,
) -> list[dict[str, Any]]:
    """Build one send per schedule + group + member + occurrence.

    Each member receives their own message in the destination group: a personal
    greeting, their own @mention tag, and their own message_logs row. This keeps
    per-member meal-plan guidance possible when a group holds multiple members
    of the same tier. Every active group_members relationship is a destination.
    """
    destinations_by_member: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for dest in destinations:
        destinations_by_member[dest["member_id"]].append(dest)

    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for schedule in schedules:
        for member in members:
            if not schedule_matches_member(schedule, member):
                continue
            occurrences = (
                [now_local.replace(second=0, microsecond=0)]
                if force_due_for_preview
                else due_occurrences(schedule, member, now_local, grace_minutes, catchup_minutes)
            )
            if not occurrences:
                continue
            member_destinations = destinations_by_member.get(member["member_id"], [])
            if not member_destinations:
                logger.warning(
                    f"[NO DESTINATION] schedule={schedule['schedule_id']} "
                    f"member={member.get('member_code') or member['member_id']}; "
                    "no active group_members relationship"
                )
                continue

            for occurrence in occurrences:
                for dest in member_destinations:
                    key = (schedule["schedule_id"], dest["group_id"], member["member_id"], occurrence)
                    if key not in grouped:
                        grouped[key] = {
                            "schedule": schedule,
                            "scheduled_at": occurrence,
                            "group_id": dest["group_id"],
                            "group_name": dest["group_name"],
                            "chat_id": dest["periskope_chat_id"],
                            "members": [],
                        }
                    candidate = grouped[key]
                    if all(existing["member_id"] != member["member_id"] for existing in candidate["members"]):
                        candidate["members"].append(member)

    candidates = list(grouped.values())
    for candidate in candidates:
        candidate["members"].sort(key=lambda m: m["member_id"])
        # Each candidate holds exactly one member, so message_logs.member_id is
        # always the actual recipient of this send.
        candidate["log_member_id"] = candidate["members"][0]["member_id"] if candidate["members"] else None
    candidates.sort(key=lambda c: (c["scheduled_at"], c["schedule"]["schedule_id"], c["group_id"]))
    return candidates


def render_template(candidate: dict[str, Any]) -> str:
    members = candidate["members"]
    names = [str(m["member_name"]).strip() for m in members if m.get("member_name")]
    if len(names) <= 1:
        display_name = names[0] if names else "there"
    elif len(names) == 2:
        display_name = f"{names[0]} and {names[1]}"
    else:
        display_name = ", ".join(names[:-1]) + f", and {names[-1]}"

    schedule = candidate["schedule"]
    first_member = members[0] if members else {}
    variables = {
        "member_name": display_name,
        "member_names": display_name,
        "first_name": names[0].split()[0] if names else "there",
        "tier_name": schedule.get("tier_name") or "",
        "phase_name": first_member.get("phase_name") or "",
        "group_name": candidate.get("group_name") or "",
    }
    content = str(schedule.get("message_content") or "")
    rendered = re.sub(
        r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}",
        lambda match: str(variables[match.group(1)]) if match.group(1) in variables else match.group(0),
        content,
    )
    unresolved = re.findall(r"\{\{\s*[^{}]+\s*\}\}", rendered)
    if unresolved:
        raise ValueError(f"Template has unresolved placeholders: {', '.join(unresolved)}")
    return rendered


def mention_footer(members: list[dict[str, Any]]) -> str:
    """Build the @mention footer for the members a message is intended for.

    A WhatsApp mention notifies the member even when the group is muted, but
    only if their exact number is a participant of the destination group.
    Members without a phone_number are ignored and produce no footer, so the
    message stays exactly as the template rendered it.

    The verified tag format is '@' followed by the international number with
    no leading plus (e.g. @919674671233); a '+', suppresses the mention.
    """
    tags = []
    for member in members:
        phone = str(member.get("phone_number") or "").strip().replace(" ", "").lstrip("+")
        if phone:
            tags.append(f"@{phone}")
    if not tags:
        return ""
    return "\n\n" + " ".join(tags)


def process_candidate(candidate: dict[str, Any], dry_run: bool, client: Any | None) -> bool:
    """Send one candidate.

    Returns True only when a live send was actually attempted, so the
    per-cycle send cap counts real attempts; guards and duplicate skips do not.
    """
    schedule = candidate["schedule"]
    try:
        content = render_template(candidate)
    except Exception as exc:
        logger.error(f"[CONFIG ERROR] {exc} | schedule={schedule['schedule_id']}")
        return False

    # The @mention footer pings the intended members even when the group is
    # muted; members without a phone_number get no footer (message unchanged).
    content += mention_footer(candidate["members"])

    message_type = str(schedule.get("message_type", "TEXT")).upper()
    media_url = schedule.get("media_url")
    if message_type not in {"TEXT", "LOCATION"} and not media_url:
        logger.warning(f"[NOT READY] schedule={schedule['schedule_id']} template={schedule['template_code']} has no media_url")
        return False
    if message_type == "LOCATION":
        logger.warning(f"[NOT READY] schedule={schedule['schedule_id']} uses LOCATION; adapter not implemented yet")
        return False

    member_labels = ", ".join(
        f"{m.get('member_name')} ({m.get('member_code') or m.get('member_id')})"
        for m in candidate["members"]
    )
    logger.info(
        f"[{'DRY RUN' if dry_run else 'LIVE'}] {candidate['scheduled_at']} "
        f"| schedule={schedule['schedule_id']} | task={schedule['task_type']} "
        f"| tier={schedule['tier_name']} | members={member_labels} "
        f"| group={candidate['group_name']} | chat_id={candidate['chat_id']} "
        f"| template={schedule['template_code']}"
    )
    if dry_run:
        logger.info(f"  rendered message: {content}")
        return False

    chat_id = str(candidate["chat_id"])
    if chat_id.startswith("DEMO_") or "DEMO_CHAT_ID" in chat_id:
        logger.warning(f"[BLOCKED DEMO DESTINATION] group={candidate['group_name']} chat_id={chat_id}")
        return False

    log_id = create_pending_log(candidate, content)
    if log_id is None:
        logger.info(
            f"[DUPLICATE SKIPPED] schedule={schedule['schedule_id']} "
            f"group={candidate['group_id']} scheduled_at={candidate['scheduled_at']}"
        )
        return False

    try:
        status, response = send_message(
            client=client,
            chat_id=candidate["chat_id"],
            message_type=message_type,
            content=content,
            media_url=media_url,
        )
        error = None
        if status == "FAILED":
            error = f"Periskope returned a failure response: {str(response)[:3500]}"
        update_log_after_send(log_id, status, response, error)
        provider_id = response.get("message_id") or response.get("id") or response.get("unique_id") or response.get("track_by")
        logger.log(
            logging.ERROR if status == "FAILED" else logging.INFO,
            f"[PROVIDER {status}] log_id={log_id} periskope_message_id={provider_id}",
        )
        return True
    except Exception as exc:
        error = (
            f"Send attempt raised {type(exc).__name__}: {exc}. "
            "The provider may have accepted the request; review before retrying."
        )
        update_log_after_send(log_id, "FAILED", {}, error)
        logger.error(f"[SEND ERROR] log_id={log_id} {error}")
        return True


def kill_switch_tripped(directory: str | None = None) -> bool:
    """True when live sends must halt for this cycle.

    Halt conditions: SENDS_ENABLED=false in the environment, or a STOP_SENDS
    file next to scheduler.py (or `directory`). Script-relative so the brake
    works under systemd regardless of WorkingDirectory. Checked every live
    cycle, so sends stop within one poll without restarting the process. Dry
    runs are unaffected.
    """
    if os.getenv("SENDS_ENABLED", "true").strip().lower() in {"false", "0", "no", "off"}:
        return True
    base = directory or str(Path(__file__).resolve().parent)
    stop_path = str(Path(base) / "STOP_SENDS")
    return os.path.exists(stop_path)


def resolve_send_cap(cli_max_sends: int | None = None) -> int:
    """Live send attempts allowed per cycle.

    --max-sends overrides the MAX_SENDS_PER_CYCLE environment value (default
    25). Zero blocks all live sends for the cycle. Dry runs are unaffected.
    """
    if cli_max_sends is not None:
        return max(0, int(cli_max_sends))
    try:
        value = int(os.getenv("MAX_SENDS_PER_CYCLE", "25"))
    except ValueError:
        return 25
    return max(0, value)


def send_heartbeat(url: str | None) -> bool | None:
    """Ping the dead-man-switch once; never raises, never blocks long.

    Returns None when no HEARTBEAT_URL is configured, True when the ping
    succeeded, and False when it failed. The dead-man-switch service (for
    example Healthchecks.io) alerts when pings stop arriving, which covers a
    dead process, a crashed server, and a database outage between cycles.
    """
    if not (url or "").strip():
        return None
    try:
        response = requests.get(url.strip(), timeout=5)
        return 200 <= response.status_code < 300
    except Exception:
        return False


def report_heartbeat() -> None:
    """Ping the dead-man-switch once per completed cycle, if configured.

    Failures are logged only on state changes (first failure, every 100th,
    and recovery) so a broken URL cannot spam the log once per cycle.
    """
    global _heartbeat_failures
    result = send_heartbeat(os.getenv("HEARTBEAT_URL"))
    if result is None:
        return
    if result:
        if _heartbeat_failures:
            logger.info(f"heartbeat ping recovered after {_heartbeat_failures} failure(s)")
        _heartbeat_failures = 0
        return
    _heartbeat_failures += 1
    if _heartbeat_failures == 1 or _heartbeat_failures % 100 == 0:
        logger.warning(
            f"heartbeat ping failed ({_heartbeat_failures} consecutive failure(s)); "
            "the dead-man-switch alerts when pings stop arriving"
        )


def report_needs_attention() -> None:
    """Print stale PENDING and recent FAILED sends so nothing fails silently.

    Failed sends are not retried automatically (the provider may have accepted
    an attempted send). A stale PENDING row usually means the process died
    between logging and sending. Both need a human decision before any retry.
    """
    rows = fetch_attention_rows()
    if not rows:
        return
    stale_pending = sum(1 for row in rows if row["status"] == "PENDING")
    failed = len(rows) - stale_pending
    logger.warning(
        f"[NEEDS ATTENTION] {stale_pending} stale PENDING (created >5m ago; send may have "
        f"crashed) and {failed} FAILED (last 24h; not auto-retried) row(s). Review before retry:"
    )
    for row in rows:
        error = str(row.get("error_message") or "").strip().replace("\n", " ")[:120]
        logger.warning(
            f"  log_id={row['message_log_id']} status={row['status']} "
            f"schedule={row['schedule_id']} group={row['group_id']} "
            f"scheduled_at={row['scheduled_at']} created_at={row['created_at']}"
            + (f" error={error}" if error else "")
        )


def candidate_attempt_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """Stable identity of one send attempt: schedule + group + member + time.

    Matches the message_logs dedup quadruple used by create_pending_log, so an
    occurrence already processed in this process run is skipped without
    another database round-trip. Restarts stay safe: the database check in
    create_pending_log remains the authoritative guard.
    """
    return (
        candidate["schedule"]["schedule_id"],
        candidate["group_id"],
        candidate["log_member_id"],
        candidate["scheduled_at"],
    )


def run_one_cycle(
    dry_run: bool,
    client: Any | None,
    grace_minutes: int,
    schedule_id_filter: int | None = None,
    member_code_filter: str | None = None,
    force_due_for_preview: bool = False,
    catchup_minutes: int = 0,
    send_cap: int | None = None,
) -> int:
    global _catchup_pending
    schedules, members, destinations = load_configuration()
    now = datetime.now(ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata")))
    now_local = now.replace(tzinfo=None, second=0, microsecond=0)
    effective_catchup = catchup_minutes if _catchup_pending else 0
    candidates = build_candidates(
        schedules, members, destinations, now_local, grace_minutes,
        force_due_for_preview, effective_catchup,
    )
    if schedule_id_filter is not None:
        candidates = [c for c in candidates if c["schedule"]["schedule_id"] == schedule_id_filter]
    if member_code_filter:
        wanted = member_code_filter.casefold()
        candidates = [
            c for c in candidates
            if any(str(m.get("member_code") or "").casefold() == wanted for m in c["members"])
        ]

    # Skip occurrences this process already handled (any outcome), so the grace
    # window no longer re-attempts them every cycle. Cap-deferred and
    # kill-switched candidates are not marked and retry on later cycles.
    candidates = [c for c in candidates if candidate_attempt_key(c) not in _attempted_candidates]

    logger.info(
        f"\nCycle at {now.isoformat(timespec='seconds')}: "
        f"{len(schedules)} active schedules, {len(members)} active tier-assigned members, "
        f"{len(candidates)} candidate(s)"
        + (" [catch-up pass]" if effective_catchup > 0 else "")
        + "."
    )

    halted = False
    if not dry_run and kill_switch_tripped():
        logger.warning(
            f"[KILL SWITCH] live sends are halted this cycle; {len(candidates)} candidate(s) "
            "skipped. Remove the STOP_SENDS file or set SENDS_ENABLED=true to resume."
        )
        candidates = []
        halted = True

    # Live sends are capped per cycle. Deferred candidates are not logged, so
    # the next cycle picks them up again inside the catch-up window.
    sends_left = send_cap if (not dry_run and send_cap is not None) else None
    cap_deferred = False
    for index, candidate in enumerate(candidates):
        if sends_left is not None and sends_left <= 0:
            logger.warning(
                f"[SEND CAP] {send_cap} live send(s) reached this cycle; "
                f"{len(candidates) - index} candidate(s) deferred to the next cycle."
            )
            cap_deferred = True
            break
        # Mark as attempted before processing: this occurrence is considered
        # exactly once per process run; the DB check stays the real guard.
        _attempted_candidates.add(candidate_attempt_key(candidate))
        if process_candidate(candidate, dry_run, client):
            if sends_left is not None:
                sends_left -= 1
    if not dry_run:
        report_needs_attention()
    if not halted and not cap_deferred:
        # The catch-up pass stays armed until a cycle completes without the
        # kill switch or the send cap deferring work, so recovery is never
        # dropped by a partial cycle.
        _catchup_pending = False
    # A completed cycle (even one that deferred or halted sends) means the
    # process and database are both alive: ping the dead-man-switch.
    report_heartbeat()
    return len(candidates)


def main() -> int:
    load_dotenv()
    level_name = str(os.getenv("LOG_LEVEL", "INFO")).upper()
    level = logging.getLevelName(level_name)
    if not isinstance(level, int):
        level = logging.INFO

    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = (log_dir / "scheduler.log").resolve()
    formatter = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename).resolve() == log_path
        for handler in root_logger.handlers
    ):
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    if not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in root_logger.handlers
    ):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    parser = argparse.ArgumentParser(description="Zyvefit outgoing message scheduler")
    parser.add_argument("--send", action="store_true", help="Actually send through Periskope. Default is dry-run.")
    parser.add_argument("--schedule-id", type=int, help="Filter to a single schedule ID.")
    parser.add_argument("--member-code", help="Filter candidates to a group containing this member code.")
    parser.add_argument(
        "--force-due-preview", action="store_true",
        help="DRY-RUN only: preview a selected schedule/member now, ignoring its due time.",
    )
    parser.add_argument(
        "--max-sends", type=int,
        help="Cap live send attempts per cycle (default: MAX_SENDS_PER_CYCLE env, else 25).",
    )
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    args = parser.parse_args()

    try:
        get_database_url()
        poll_seconds = max(5, int(os.getenv("POLL_SECONDS", "30")))
        grace_minutes = max(0, int(os.getenv("MISFIRE_GRACE_MINUTES", "5")))
        catchup_minutes = max(0, int(os.getenv("CATCHUP_MINUTES", "1440")))
        send_cap = resolve_send_cap(args.max_sends)
        dry_run = not args.send
        if args.force_due_preview and args.send:
            raise RuntimeError("--force-due-preview is dry-run only; remove --send.")
        if args.force_due_preview and (args.schedule_id is None or not args.member_code):
            raise RuntimeError("--force-due-preview requires both --schedule-id and --member-code.")
        if args.send and args.once and (args.schedule_id is None or not args.member_code):
            raise RuntimeError("A one-shot LIVE send requires both --schedule-id and --member-code.")
        client = None if dry_run else build_client()
        logger.info(f"Zyvefit scheduler starting | mode={'DRY RUN' if dry_run else 'LIVE SEND'}")
        logger.info(
            f"Timezone={os.getenv('APP_TIMEZONE', 'Asia/Kolkata')} | poll={poll_seconds}s | "
            f"grace={grace_minutes}m | catchup={catchup_minutes}m | max_live_sends_per_cycle={send_cap}"
        )
        if not dry_run:
            logger.info(
                "Kill switch: create a STOP_SENDS file next to scheduler.py "
                "(or set SENDS_ENABLED=false) to halt live sends within one poll."
            )
        cycle_failures = 0
        while True:
            try:
                run_one_cycle(
                    dry_run, client, grace_minutes, args.schedule_id, args.member_code,
                    args.force_due_preview, catchup_minutes, send_cap,
                )
                if cycle_failures:
                    logger.info(f"cycle recovered after {cycle_failures} failed cycle(s)")
                    cycle_failures = 0
            except Exception as exc:
                cycle_failures += 1
                # Log the first failure and then every 10th, so a database
                # outage cannot spam the log once per poll; the heartbeat
                # dead-man-switch is what alerts during a long outage.
                if cycle_failures == 1 or cycle_failures % 10 == 0:
                    logger.error(
                        f"[CYCLE ERROR] {type(exc).__name__}: {exc} "
                        f"({cycle_failures} consecutive failed cycle(s); "
                        "logging every 10th until recovered)"
                    )
            if args.once:
                return 0
            time_module.sleep(poll_seconds)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped.")
        return 0
    except Exception as exc:
        logger.error(f"[STARTUP ERROR] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
