#!/usr/bin/env python3
"""Import members and their Periskope group assignments from Members.xlsx.

Default behaviour is a read-only dry run. Pass --apply to commit changes.
This script expects to live at <project-root>/scripts/import_members.py and
uses the existing <project-root>/db.py connect_database() helper.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMPORT_DIR = PROJECT_ROOT / "imports"
DEFAULT_AUDIT_DIR = PROJECT_ROOT / "logs" / "member_import"
PHASE_DEFAULT_ID = 16

REQUIRED_HEADERS = {
    "membercode": "Member Code",
    "fullname": "Full Name",
    "phonenumber": "Phone Number",
    "firstname": "First Name",
    "joiningdate": "Joining Date",
    "membershipstatus": "Membership Status",
    "phases": "Phases",
    "tier": "Tier",
    "periskopegroupchatid": "Periskope Group Chat ID",
}
HEADER_ALIASES = {
    "periscopegroupchatid": "periskopegroupchatid",
    "whatsappgroupchatid": "periskopegroupchatid",
    "phase": "phases",
}
GROUP_CHAT_ID_RE = re.compile(r"^[0-9]+@g\.us$")


class ImportValidationError(Exception):
    """Raised when workbook data cannot safely be imported."""


@dataclass
class MemberRecord:
    member_code: str
    full_name: str | None
    phone_number: str | None
    first_name: str
    joining_date: date
    is_active: bool
    phase_input: str
    tier_input: str
    source_rows: list[int] = field(default_factory=list)
    group_chat_ids: list[str] = field(default_factory=list)
    phase_id: int | None = None
    phase_name: str | None = None
    tier_id: int | None = None
    tier_name: str | None = None


@dataclass
class WorkbookData:
    sheet_name: str
    records: dict[str, MemberRecord]
    group_member_codes: dict[str, list[str]]


@dataclass
class ImportSummary:
    member_inserted: int = 0
    member_updated: int = 0
    member_unchanged: int = 0
    groups_inserted: int = 0
    groups_updated: int = 0
    groups_unchanged: int = 0
    links_inserted: int = 0
    links_reactivated: int = 0
    links_ended: int = 0
    links_unchanged: int = 0
    inactive_new_links_skipped: int = 0
    audit_records: list[dict[str, Any]] = field(default_factory=list)


def canonical_header(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def cell_as_text(value: Any) -> str | None:
    """Convert Excel text/numeric identifiers to predictable strings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, ".15g")
    return str(value).strip() or None


def normalize_phone(value: Any) -> str | None:
    """Keep digits only; do not infer or add a country calling code."""
    raw = cell_as_text(value)
    if raw is None:
        return None
    digits = re.sub(r"[^0-9]", "", raw)
    return digits or None


def parse_joining_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = from_excel(value)
            if isinstance(converted, datetime):
                return converted.date()
            if isinstance(converted, date):
                return converted
        except (OverflowError, TypeError, ValueError):
            pass
    text = clean_text(value)
    if not text:
        raise ValueError("Joining Date is blank")
    for fmt in (
        "%d-%b-%y",
        "%d-%b-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"unsupported Joining Date {text!r}; use an Excel date or a format such as 15-Jul-20"
    )


def parse_membership_status(value: Any) -> bool:
    text = clean_text(value)
    if not text:
        raise ValueError("Membership Status is blank")
    normalized = text.casefold()
    if normalized == "active":
        return True
    if normalized == "inactive":
        return False
    raise ValueError(f"Membership Status must be Active or Inactive, got {text!r}")


def parse_group_chat_id(value: Any) -> str:
    """Validate the group ID without modifying its Excel value."""
    if value is None:
        raise ValueError("Periskope Group Chat ID is blank")
    if not isinstance(value, str):
        raise ValueError("Periskope Group Chat ID must be stored as text in Excel")
    if value == "":
        raise ValueError("Periskope Group Chat ID is blank")
    if value != value.strip():
        raise ValueError(
            "Periskope Group Chat ID has leading/trailing whitespace; clean the Excel cell. "
            "The importer preserves this ID exactly as supplied."
        )
    if not GROUP_CHAT_ID_RE.fullmatch(value):
        raise ValueError(
            f"invalid group ID {value!r}; expected digits followed by @g.us (not @c.us)"
        )
    return value


def same_value(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return left.strip().casefold() == right.strip().casefold()
    return left == right


def merge_duplicate_member(existing: MemberRecord, incoming: MemberRecord, row_number: int) -> None:
    """Merge another group row for a member, rejecting conflicting member data."""
    comparisons = (
        ("First Name", existing.first_name, incoming.first_name),
        ("Joining Date", existing.joining_date, incoming.joining_date),
        ("Membership Status", existing.is_active, incoming.is_active),
        ("Phases", existing.phase_input, incoming.phase_input),
        ("Tier", existing.tier_input, incoming.tier_input),
    )
    conflicts = [label for label, old, new in comparisons if not same_value(old, new)]

    for label, old, new in (
        ("Full Name", existing.full_name, incoming.full_name),
        ("Phone Number", existing.phone_number, incoming.phone_number),
    ):
        if old and new and not same_value(old, new):
            conflicts.append(label)

    if conflicts:
        rows = ", ".join(str(number) for number in existing.source_rows + [row_number])
        raise ImportValidationError(
            f"Member Code {existing.member_code!r} has conflicting values in Excel rows "
            f"{rows}: {', '.join(conflicts)}. Correct the duplicate rows before importing."
        )

    if not existing.full_name and incoming.full_name:
        existing.full_name = incoming.full_name
    if not existing.phone_number and incoming.phone_number:
        existing.phone_number = incoming.phone_number
    existing.source_rows.append(row_number)
    if incoming.group_chat_ids[0] not in existing.group_chat_ids:
        existing.group_chat_ids.append(incoming.group_chat_ids[0])


def read_workbook(path: Path, sheet_name: str | None = None) -> WorkbookData:
    if not path.is_file():
        raise FileNotFoundError(f"Excel file not found: {path}")
    if path.suffix.casefold() != ".xlsx":
        raise ImportValidationError("Only .xlsx workbooks are supported")

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                raise ImportValidationError(
                    f"Worksheet {sheet_name!r} not found. Available sheets: {', '.join(workbook.sheetnames)}"
                )
            sheet = workbook[sheet_name]
        else:
            sheet = workbook.active

        iterator = sheet.iter_rows(values_only=True)
        header_row_number = None
        headers: list[Any] | None = None
        for row_number, row in enumerate(iterator, start=1):
            if any(value is not None and str(value).strip() for value in row):
                headers = list(row)
                header_row_number = row_number
                break
        if headers is None:
            raise ImportValidationError("The selected worksheet is empty")

        header_indexes: dict[str, int] = {}
        for index, raw_header in enumerate(headers):
            normalized = canonical_header(raw_header)
            if normalized in HEADER_ALIASES:
                normalized = HEADER_ALIASES[normalized]
            if not normalized:
                continue
            if normalized in header_indexes:
                raise ImportValidationError(
                    f"Duplicate Excel column heading {raw_header!r} in the header row"
                )
            header_indexes[normalized] = index

        missing = [
            label for key, label in REQUIRED_HEADERS.items() if key not in header_indexes
        ]
        if missing:
            raise ImportValidationError(
                "Missing required Excel columns: " + ", ".join(missing)
            )

        records: dict[str, MemberRecord] = {}
        group_member_codes: dict[str, list[str]] = defaultdict(list)
        errors: list[str] = []

        def value_for(row: tuple[Any, ...], key: str) -> Any:
            index = header_indexes[key]
            return row[index] if index < len(row) else None

        for row_number, row in enumerate(iterator, start=header_row_number + 1):
            if not any(value is not None and str(value).strip() for value in row):
                continue
            try:
                member_code = cell_as_text(value_for(row, "membercode"))
                if not member_code:
                    raise ValueError("Member Code is blank")
                first_name = clean_text(value_for(row, "firstname"))
                if not first_name:
                    raise ValueError("First Name is blank")
                full_name = clean_text(value_for(row, "fullname"))
                phone_number = normalize_phone(value_for(row, "phonenumber"))
                joining_date = parse_joining_date(value_for(row, "joiningdate"))
                is_active = parse_membership_status(value_for(row, "membershipstatus"))
                phase_input = clean_text(value_for(row, "phases"))
                tier_input = clean_text(value_for(row, "tier"))
                if not phase_input:
                    raise ValueError("Phases is blank")
                if not tier_input:
                    raise ValueError("Tier is blank")
                group_chat_id = parse_group_chat_id(value_for(row, "periskopegroupchatid"))

                incoming = MemberRecord(
                    member_code=member_code,
                    full_name=full_name,
                    phone_number=phone_number,
                    first_name=first_name,
                    joining_date=joining_date,
                    is_active=is_active,
                    phase_input=phase_input,
                    tier_input=tier_input,
                    source_rows=[row_number],
                    group_chat_ids=[group_chat_id],
                )
                if member_code in records:
                    merge_duplicate_member(records[member_code], incoming, row_number)
                else:
                    records[member_code] = incoming
                if member_code not in group_member_codes[group_chat_id]:
                    group_member_codes[group_chat_id].append(member_code)
            except (ValueError, TypeError) as exc:
                errors.append(f"Excel row {row_number}: {exc}")

        if errors:
            preview = "\n".join(f"  - {error}" for error in errors[:50])
            more = f"\n  ... and {len(errors) - 50} more error(s)" if len(errors) > 50 else ""
            raise ImportValidationError(
                f"Workbook validation failed with {len(errors)} row error(s):\n{preview}{more}"
            )
        if not records:
            raise ImportValidationError("No member records were found below the header row")

        return WorkbookData(
            sheet_name=sheet.title,
            records=records,
            group_member_codes=dict(group_member_codes),
        )
    finally:
        workbook.close()


def lookup_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def resolve_foreign_keys(conn: Any, workbook_data: WorkbookData) -> None:
    tier_rows = conn.execute("SELECT tier_id, tier_name FROM tiers ORDER BY tier_id").fetchall()
    phase_rows = conn.execute("SELECT phase_id, phase_name FROM phases ORDER BY phase_number").fetchall()

    tier_map: dict[str, dict[str, Any]] = {}
    phase_map: dict[str, dict[str, Any]] = {}
    for row in tier_rows:
        key = lookup_key(row["tier_name"])
        if key in tier_map:
            raise ImportValidationError(
                f"The tiers table has names that differ only by case/spacing: {row['tier_name']!r}. "
                "Make the lookup names unambiguous before importing."
            )
        tier_map[key] = row
    for row in phase_rows:
        key = lookup_key(row["phase_name"])
        if key in phase_map:
            raise ImportValidationError(
                f"The phases table has names that differ only by case/spacing: {row['phase_name']!r}. "
                "Make the lookup names unambiguous before importing."
            )
        phase_map[key] = row

    if not any(int(row["phase_id"]) == PHASE_DEFAULT_ID for row in phase_rows):
        raise ImportValidationError(
            f"Operational phase_id default {PHASE_DEFAULT_ID} does not exist in phases. "
            "Create/verify that phase before importing."
        )

    errors: list[str] = []
    for record in workbook_data.records.values():
        tier = tier_map.get(lookup_key(record.tier_input))
        phase = phase_map.get(lookup_key(record.phase_input))
        if tier is None:
            errors.append(
                f"Member {record.member_code}: Tier {record.tier_input!r} does not exist in tiers.tier_name"
            )
        if phase is None:
            errors.append(
                f"Member {record.member_code}: Phase {record.phase_input!r} does not exist in phases.phase_name"
            )
        if tier and phase:
            record.tier_id = int(tier["tier_id"])
            record.tier_name = str(tier["tier_name"])
            record.phase_id = int(phase["phase_id"])
            record.phase_name = str(phase["phase_name"])

    if errors:
        preview = "\n".join(f"  - {error}" for error in errors[:50])
        more = f"\n  ... and {len(errors) - 50} more error(s)" if len(errors) > 50 else ""
        raise ImportValidationError(
            f"Tier/phase lookup failed with {len(errors)} error(s):\n{preview}{more}"
        )


def build_group_names(workbook_data: WorkbookData) -> dict[str, str]:
    result: dict[str, str] = {}
    for group_chat_id, member_codes in workbook_data.group_member_codes.items():
        ordered_members = [workbook_data.records[code] for code in member_codes]
        member_labels = [
            f"{record.first_name} ({record.phase_name})" for record in ordered_members
        ]
        ordered_tiers = [str(record.tier_name) for record in ordered_members]
        result[group_chat_id] = f"{' + '.join(member_labels)} ({', '.join(ordered_tiers)})"
    return result


def check_schema(conn: Any) -> None:
    required = {
        "members": {
            "member_id", "member_code", "member_name", "full_name", "phone_number",
            "joining_date", "tier_id", "phase_id", "actual_phase_id", "phase_override",
            "is_active", "created_at", "updated_at",
        },
        "whatsapp_groups": {"group_id", "periskope_chat_id", "group_name", "created_at", "updated_at"},
        "group_members": {"group_id", "member_id", "joined_at", "left_at"},
        "tiers": {"tier_id", "tier_name"},
        "phases": {"phase_id", "phase_name", "phase_number"},
    }
    missing: list[str] = []
    for table, expected_columns in required.items():
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s
            """,
            (table,),
        ).fetchall()
        actual = {row["column_name"] for row in rows}
        if not actual:
            missing.append(f"table {table}")
            continue
        for column in sorted(expected_columns - actual):
            missing.append(f"{table}.{column}")
    if missing:
        raise ImportValidationError(
            "Database schema is missing required objects: " + ", ".join(missing) +
            ". Run scripts/migrations/add_member_import_columns.sql first and verify the existing table definitions."
        )


def fetch_one_member(conn: Any, member_code: str, lock: bool) -> dict[str, Any] | None:
    sql = "SELECT * FROM members WHERE member_code = %s"
    if lock:
        sql += " FOR UPDATE"
    return conn.execute(sql, (member_code,)).fetchone()


def member_values(record: MemberRecord) -> dict[str, Any]:
    assert record.tier_id is not None and record.phase_id is not None
    return {
        "member_name": record.first_name,
        "full_name": record.full_name,
        "phone_number": record.phone_number,
        "joining_date": record.joining_date,
        "tier_id": record.tier_id,
        "actual_phase_id": record.phase_id,
        "is_active": record.is_active,
    }


def member_row_changed(before: dict[str, Any], desired: dict[str, Any]) -> bool:
    for key, value in desired.items():
        # Blank optional Excel cells do not erase existing values.
        if key in {"full_name", "phone_number"} and value is None:
            continue
        if before.get(key) != value:
            return True
    return False


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def add_audit(
    summary: ImportSummary,
    table: str,
    operation: str,
    key: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    source: dict[str, Any] | None = None,
) -> None:
    summary.audit_records.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "table": table,
            "operation": operation,
            "key": json_safe(key),
            "source": json_safe(source or {}),
            "before": json_safe(before),
            "after": json_safe(after),
        }
    )


def execute_member_import(
    conn: Any,
    workbook_data: WorkbookData,
    apply_changes: bool,
) -> tuple[ImportSummary, dict[str, int | None], dict[str, int]]:
    summary = ImportSummary()
    member_ids: dict[str, int | None] = {}

    for member_code, record in workbook_data.records.items():
        if apply_changes:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (f"zyvefit-member-import:{member_code}",))
        before = fetch_one_member(conn, member_code, lock=apply_changes)
        desired = member_values(record)
        source = {"sheet": workbook_data.sheet_name, "excel_rows": record.source_rows}

        if before is None:
            if not record.full_name:
                raise ImportValidationError(
                    f"New member {member_code!r} (Excel rows {record.source_rows}) has a blank Full Name. "
                    "Provide Full Name before inserting a new member."
                )
            if apply_changes:
                after = conn.execute(
                    """
                    INSERT INTO members (
                        member_code, member_name, full_name, phone_number,
                        joining_date, tier_id, phase_id, actual_phase_id, is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        record.member_code,
                        desired["member_name"],
                        desired["full_name"],
                        desired["phone_number"],
                        desired["joining_date"],
                        desired["tier_id"],
                        PHASE_DEFAULT_ID,
                        desired["actual_phase_id"],
                        desired["is_active"],
                    ),
                ).fetchone()
                member_ids[member_code] = int(after["member_id"])
                add_audit(summary, "members", "INSERT", {"member_code": member_code}, None, after, source)
            else:
                after = None
                member_ids[member_code] = None
            summary.member_inserted += 1
            continue

        member_ids[member_code] = int(before["member_id"])
        if member_row_changed(before, desired):
            if apply_changes:
                after = conn.execute(
                    """
                    UPDATE members
                    SET member_name = %s,
                        full_name = COALESCE(%s, full_name),
                        phone_number = COALESCE(%s, phone_number),
                        joining_date = %s,
                        tier_id = %s,
                        actual_phase_id = %s,
                        is_active = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE member_id = %s
                    RETURNING *
                    """,
                    (
                        desired["member_name"],
                        desired["full_name"],
                        desired["phone_number"],
                        desired["joining_date"],
                        desired["tier_id"],
                        desired["actual_phase_id"],
                        desired["is_active"],
                        before["member_id"],
                    ),
                ).fetchone()
                add_audit(summary, "members", "UPDATE", {"member_code": member_code}, before, after, source)
            summary.member_updated += 1
        else:
            after = before
            if apply_changes:
                add_audit(summary, "members", "UNCHANGED", {"member_code": member_code}, before, after, source)
            summary.member_unchanged += 1

    group_names = build_group_names(workbook_data)
    group_ids: dict[str, int] = {}
    for group_chat_id, group_name in group_names.items():
        if apply_changes:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (f"zyvefit-group-import:{group_chat_id}",))
        before = conn.execute(
            "SELECT * FROM whatsapp_groups WHERE periskope_chat_id = %s" + (" FOR UPDATE" if apply_changes else ""),
            (group_chat_id,),
        ).fetchone()
        if before is None:
            if apply_changes:
                after = conn.execute(
                    """
                    INSERT INTO whatsapp_groups (periskope_chat_id, group_name)
                    VALUES (%s, %s)
                    RETURNING *
                    """,
                    (group_chat_id, group_name),
                ).fetchone()
                group_ids[group_chat_id] = int(after["group_id"])
                add_audit(
                    summary, "whatsapp_groups", "INSERT", {"periskope_chat_id": group_chat_id}, None, after,
                    {"sheet": workbook_data.sheet_name},
                )
            else:
                group_ids[group_chat_id] = -1
            summary.groups_inserted += 1
        else:
            group_ids[group_chat_id] = int(before["group_id"])
            if before.get("group_name") != group_name:
                if apply_changes:
                    after = conn.execute(
                        """
                        UPDATE whatsapp_groups
                        SET group_name = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE group_id = %s
                        RETURNING *
                        """,
                        (group_name, before["group_id"]),
                    ).fetchone()
                    add_audit(
                        summary, "whatsapp_groups", "UPDATE", {"periskope_chat_id": group_chat_id}, before, after,
                        {"sheet": workbook_data.sheet_name},
                    )
                summary.groups_updated += 1
            else:
                if apply_changes:
                    add_audit(
                        summary, "whatsapp_groups", "UNCHANGED", {"periskope_chat_id": group_chat_id}, before, before,
                        {"sheet": workbook_data.sheet_name},
                    )
                summary.groups_unchanged += 1

    known_member_ids = [value for value in member_ids.values() if value is not None]
    existing_links: dict[tuple[int, int], dict[str, Any]] = {}
    if known_member_ids:
        rows = conn.execute(
            "SELECT * FROM group_members WHERE member_id = ANY(%s)" + (" FOR UPDATE" if apply_changes else ""),
            (known_member_ids,),
        ).fetchall()
        existing_links = {
            (int(row["group_id"]), int(row["member_id"])): row for row in rows
        }

    for member_code, record in workbook_data.records.items():
        member_id = member_ids[member_code]
        if member_id is None:
            # Preview mode: there is no generated member_id for new rows.
            if record.is_active:
                summary.links_inserted += len(record.group_chat_ids)
            else:
                summary.inactive_new_links_skipped += len(record.group_chat_ids)
            continue

        expected_group_ids = {
            group_ids[group_chat_id] for group_chat_id in record.group_chat_ids
            if group_chat_id in group_ids and group_ids[group_chat_id] > 0
        }
        current_for_member = {
            key: row for key, row in existing_links.items() if key[1] == member_id
        }
        source = {"sheet": workbook_data.sheet_name, "excel_rows": record.source_rows}

        # The workbook is the complete group-assignment list for each imported member.
        # Close active links that no longer appear in that member's Excel rows.
        for (group_id, linked_member_id), before in current_for_member.items():
            if before.get("left_at") is None and group_id not in expected_group_ids:
                if apply_changes:
                    after = conn.execute(
                        """
                        UPDATE group_members
                        SET left_at = CURRENT_TIMESTAMP
                        WHERE group_id = %s AND member_id = %s
                        RETURNING *
                        """,
                        (group_id, linked_member_id),
                    ).fetchone()
                    add_audit(
                        summary, "group_members", "END", {"group_id": group_id, "member_id": linked_member_id},
                        before, after, source,
                    )
                summary.links_ended += 1

        # Only active members receive new/reactivated group links. Existing links for
        # inactive members remain historical/current records; members.is_active is the
        # scheduler's main eligibility flag. A changed old group above still gets left_at.
        for group_chat_id in record.group_chat_ids:
            group_id = group_ids[group_chat_id]
            if group_id <= 0:
                # A new group has no database ID during dry-run; still count its planned link.
                if record.is_active:
                    summary.links_inserted += 1
                else:
                    summary.inactive_new_links_skipped += 1
                continue
            key = (group_id, member_id)
            before = existing_links.get(key)
            if before is None:
                if not record.is_active:
                    summary.inactive_new_links_skipped += 1
                    continue
                if apply_changes:
                    after = conn.execute(
                        """
                        INSERT INTO group_members (group_id, member_id)
                        VALUES (%s, %s)
                        ON CONFLICT (group_id, member_id) DO NOTHING
                        RETURNING *
                        """,
                        (group_id, member_id),
                    ).fetchone()
                    if after is None:
                        after = conn.execute(
                            "SELECT * FROM group_members WHERE group_id = %s AND member_id = %s",
                            (group_id, member_id),
                        ).fetchone()
                    add_audit(
                        summary, "group_members", "INSERT", {"group_id": group_id, "member_id": member_id},
                        None, after, source,
                    )
                summary.links_inserted += 1
            elif before.get("left_at") is not None and record.is_active:
                if apply_changes:
                    after = conn.execute(
                        """
                        UPDATE group_members
                        SET joined_at = CURRENT_TIMESTAMP, left_at = NULL
                        WHERE group_id = %s AND member_id = %s
                        RETURNING *
                        """,
                        (group_id, member_id),
                    ).fetchone()
                    add_audit(
                        summary, "group_members", "REACTIVATE", {"group_id": group_id, "member_id": member_id},
                        before, after, source,
                    )
                summary.links_reactivated += 1
            else:
                summary.links_unchanged += 1

    return summary, member_ids, group_ids


def get_timezone() -> ZoneInfo:
    timezone_name = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Invalid APP_TIMEZONE value: {timezone_name!r}") from exc


def write_staged_audit(records: list[dict[str, Any]], audit_dir: Path) -> tuple[Path, Path]:
    audit_dir.mkdir(parents=True, exist_ok=True)
    tz = get_timezone()
    now = datetime.now(tz)
    filename = f"member_import_{now.strftime('%Y%m%d_%H%M%S')}_{now.microsecond:06d}.jsonl"
    final_path = audit_dir / filename
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{filename}.",
        suffix=".pending",
        dir=audit_dir,
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return temp_path, final_path


def print_summary(summary: ImportSummary, apply_changes: bool, audit_path: Path | None = None) -> None:
    mode = "APPLIED" if apply_changes else "DRY RUN — NO DATABASE CHANGES"
    print(f"\nMember import result: {mode}")
    print(
        "Members: "
        f"insert={summary.member_inserted}, update={summary.member_updated}, "
        f"unchanged={summary.member_unchanged}"
    )
    print(
        "WhatsApp groups: "
        f"create={summary.groups_inserted}, rename={summary.groups_updated}, "
        f"unchanged={summary.groups_unchanged}"
    )
    print(
        "Group memberships: "
        f"add={summary.links_inserted}, reactivate={summary.links_reactivated}, "
        f"set_left_at={summary.links_ended}, unchanged={summary.links_unchanged}, "
        f"inactive_new_links_skipped={summary.inactive_new_links_skipped}"
    )
    if audit_path:
        print(f"Audit log: {audit_path}")


def resolve_workbook_path(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (Path.cwd() / path).resolve()
    candidates = [DEFAULT_IMPORT_DIR / "Members.xlsx", PROJECT_ROOT / "Members.xlsx"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_connection_helper():
    # Make `import db` work when invoked as `python scripts/import_members.py`.
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from db import connect_database  # imported after .env has been loaded
    return connect_database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import/update Zyvefit members and WhatsApp group memberships from Members.xlsx"
    )
    parser.add_argument("--file", help="Path to Members.xlsx (default: imports/Members.xlsx, then project-root Members.xlsx)")
    parser.add_argument("--sheet", help="Worksheet name (default: active worksheet)")
    parser.add_argument("--apply", action="store_true", help="Commit changes. Without this flag, the script is read-only dry-run.")
    parser.add_argument("--audit-dir", help="Audit directory (default: logs/member_import)")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    workbook_path = resolve_workbook_path(args.file)
    audit_dir = Path(args.audit_dir).expanduser() if args.audit_dir else DEFAULT_AUDIT_DIR
    if not audit_dir.is_absolute():
        audit_dir = (Path.cwd() / audit_dir).resolve()

    try:
        workbook_data = read_workbook(workbook_path, args.sheet)
        print(
            f"Read {len(workbook_data.records)} unique member(s) and "
            f"{len(workbook_data.group_member_codes)} WhatsApp group(s) "
            f"from {workbook_path} [{workbook_data.sheet_name}]."
        )

        connect_database = load_connection_helper()
        conn = connect_database(dict_rows=True)
        staged_audit: Path | None = None
        final_audit: Path | None = None
        try:
            if args.apply:
                try:
                    with conn.transaction():
                        check_schema(conn)
                        resolve_foreign_keys(conn, workbook_data)
                        summary, _member_ids, _group_ids = execute_member_import(conn, workbook_data, True)
                        staged_audit, final_audit = write_staged_audit(summary.audit_records, audit_dir)
                except Exception:
                    # If the database transaction did not commit, discard its staged audit.
                    if staged_audit is not None:
                        staged_audit.unlink(missing_ok=True)
                    raise
                # The DB transaction has committed. Rename the already-fsynced audit file.
                try:
                    os.replace(staged_audit, final_audit)
                except OSError as exc:
                    print(
                        "WARNING: DATABASE COMMITTED, but the audit file could not be finalized. "
                        f"The staged audit remains at {staged_audit}. Error: {exc}",
                        file=sys.stderr,
                    )
                    print_summary(summary, True, staged_audit)
                    return 2
                print_summary(summary, True, final_audit)
            else:
                with conn.transaction():
                    conn.execute("SET TRANSACTION READ ONLY")
                    check_schema(conn)
                    resolve_foreign_keys(conn, workbook_data)
                    summary, _member_ids, _group_ids = execute_member_import(conn, workbook_data, False)
                print_summary(summary, False)
                print("Review the counts above. To commit the same workbook, rerun with --apply.")
        finally:
            conn.close()
        return 0
    except (FileNotFoundError, ImportValidationError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"IMPORT FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("No partial database changes are committed; the transaction is rolled back.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
