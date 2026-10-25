from __future__ import annotations

import logging
import importlib.util
import mimetypes
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.parse import urlparse

import psycopg
from psycopg import errors, sql
from psycopg.rows import dict_row
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
# This is a local-development build. Explicitly load the .env beside api.py
# and let it override stale DATABASE_URL values exported in the shell. Without
# override=True, load_dotenv keeps pre-existing shell values and may silently
# connect as the wrong PostgreSQL user/database after .env is edited.
load_dotenv(dotenv_path=ROOT / ".env", override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("zyvefit.api")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(ROOT / "data" / "uploads"))).expanduser()
if not UPLOAD_DIR.is_absolute():
    UPLOAD_DIR = (ROOT / UPLOAD_DIR).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_SCHEMA = os.getenv("DATABASE_SCHEMA", "public").strip() or "public"
ALLOW_DB_WRITES = os.getenv("ALLOW_DB_WRITES", "false").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_LIVE_WHATSAPP_SENDS = os.getenv("ENABLE_LIVE_WHATSAPP_SENDS", "false").strip().lower() in {"1", "true", "yes", "on"}
WHATSAPP_ALLOWED_CHAT_IDS_RAW = os.getenv("WHATSAPP_ALLOWED_CHAT_IDS", "").strip()
LIVE_SENDS_REQUIRED_DATABASE = os.getenv("LIVE_SENDS_REQUIRED_DATABASE", "zyvefit_portal_test").strip()
MAX_UPLOAD_MB = max(1, min(int(os.getenv("MAX_UPLOAD_MB", "25")), 100))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", DATABASE_SCHEMA):
    raise RuntimeError("DATABASE_SCHEMA must be a simple PostgreSQL schema identifier, such as public")

app = FastAPI(title="Zyvefit Nutritionist Console API", version="0.1.0", docs_url="/api/docs", redoc_url=None)

# Values accepted by the current Zyvefit templates table.
TYPE_TO_DB = {
    "text": "TEXT", "image": "IMAGE", "video": "VIDEO",
    "audio": "AUDIO", "document": "DOCUMENT", "pdf": "DOCUMENT", "location": "LOCATION",
}
TYPE_FROM_DB = {"TEXT": "Text", "IMAGE": "Image", "VIDEO": "Video", "AUDIO": "Audio", "DOCUMENT": "Document", "LOCATION": "Location"}
TIERS = ("Foundation", "Pro", "Max", "Ultra")
SCOPE_TO_DB = {"Shared": "SHARED", "Member-specific": "MEMBER"}
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus",
    ".mp4", ".mov", ".webm", ".m4v",
    ".txt", ".csv", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}


def qtable(name: str) -> sql.Composed:
    return sql.SQL(".").join((sql.Identifier(DATABASE_SCHEMA), sql.Identifier(name)))


@contextmanager
def db() -> Iterator[psycopg.Connection]:
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured. Copy .env.example to .env and configure it locally.")
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=4, row_factory=dict_row) as conn:
            yield conn
    except HTTPException:
        raise
    except psycopg.OperationalError as exc:
        log.warning("Database connection failed: %s", exc.__class__.__name__)
        raise HTTPException(status_code=503, detail="Could not connect to PostgreSQL. Check DATABASE_URL, the local service, and database permissions.") from exc


def get_columns(cur: psycopg.Cursor, table_name: str) -> set[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
        (DATABASE_SCHEMA, table_name),
    )
    return {row["column_name"] for row in cur.fetchall()}


def table_exists(cur: psycopg.Cursor, table_name: str) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s) AS present",
        (DATABASE_SCHEMA, table_name),
    )
    return bool(cur.fetchone()["present"])


def normalize_live_chat_id(value: str, audience_mode: Literal["member", "group"]) -> str:
    """Normalize contact phone IDs, but never rewrite a group ID."""
    candidate = (value or "").strip()
    if not candidate:
        raise HTTPException(status_code=422, detail="The selected recipient has no WhatsApp chat ID.")
    if audience_mode == "group":
        if not candidate.endswith("@g.us"):
            raise HTTPException(status_code=422, detail="The selected group's periskope_chat_id must end in @g.us.")
        return candidate
    if candidate.endswith(("@c.us", "@lid", "@s.whatsapp.net")):
        return candidate
    digits = re.sub(r"\D", "", candidate)
    if not 11 <= len(digits) <= 15:
        raise HTTPException(status_code=422, detail="The selected member has no valid international WhatsApp number or chat ID.")
    return f"{digits}@c.us"


def allowed_live_chat_ids() -> set[str]:
    """Normalize entries in WHATSAPP_ALLOWED_CHAT_IDS using the same rules as DB recipients."""
    allowed: set[str] = set()
    for raw in WHATSAPP_ALLOWED_CHAT_IDS_RAW.split(","):
        value = raw.strip()
        if not value:
            continue
        try:
            mode: Literal["member", "group"] = "group" if value.endswith("@g.us") else "member"
            allowed.add(normalize_live_chat_id(value, mode))
        except HTTPException:
            # Invalid allowlist entries are ignored; they never widen access.
            continue
    return allowed


def live_send_configuration_issues() -> list[str]:
    """Return human-readable blockers without exposing credentials."""
    issues: list[str] = []
    if not ENABLE_LIVE_WHATSAPP_SENDS:
        issues.append("ENABLE_LIVE_WHATSAPP_SENDS is false.")
    if not (os.getenv("PERISKOPE_API_KEY") or "").strip():
        issues.append("PERISKOPE_API_KEY is missing.")
    phone = re.sub(r"\D", "", os.getenv("PERISKOPE_PHONE", ""))
    if not 11 <= len(phone) <= 15:
        issues.append("PERISKOPE_PHONE is missing or is not an international phone number.")
    if not allowed_live_chat_ids():
        issues.append("WHATSAPP_ALLOWED_CHAT_IDS is empty or contains no valid recipient IDs.")
    if os.getenv("SENDS_ENABLED", "true").strip().lower() in {"false", "0", "no", "off"}:
        issues.append("SENDS_ENABLED is false (the shared scheduler/API kill switch is active).")
    if (ROOT / "STOP_SENDS").exists():
        issues.append("STOP_SENDS exists beside api.py.")
    try:
        if importlib.util.find_spec("periskope_adapter") is None:
            issues.append("periskope_adapter.py is not importable from this API environment.")
        if importlib.util.find_spec("Periskope") is None:
            issues.append("Periskope.py is not importable from this API environment.")
    except (ImportError, ModuleNotFoundError, ValueError):
        issues.append("The existing Periskope adapter/client could not be located by this API environment.")
    return issues


def live_send_log_schema_ready(cur: psycopg.Cursor) -> bool:
    """Manual sends need nullable scheduler/member/group links so the log is truthful."""
    if not table_exists(cur, "message_logs"):
        return False
    cols = get_columns(cur, "message_logs")
    required = {"message_log_id", "member_id", "group_id", "schedule_id", "message_type", "message_content", "status", "scheduled_at", "created_at"}
    if not required.issubset(cols):
        return False
    cur.execute(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name='message_logs' AND column_name = ANY(%s)",
        (DATABASE_SCHEMA, ["member_id", "group_id", "schedule_id"]),
    )
    nullability = {row["column_name"]: row["is_nullable"] for row in cur.fetchall()}
    return all(nullability.get(name) == "YES" for name in ("member_id", "group_id", "schedule_id"))


def inspect_schema(cur: psycopg.Cursor) -> dict[str, Any]:
    expected = {
        "tiers": {"tier_id", "tier_name"},
        "phases": {"phase_id", "phase_name", "phase_number"},
        "members": {"member_id", "member_code", "member_name", "tier_id", "phase_id", "is_active"},
        "whatsapp_groups": {"group_id", "group_name", "periskope_chat_id"},
        "templates": {"template_id", "template_code", "template_name", "message_type", "message_content", "media_url", "language"},
    }
    tables: dict[str, Any] = {}
    missing: list[str] = []
    for name, required in expected.items():
        exists = table_exists(cur, name)
        cols = get_columns(cur, name) if exists else set()
        lacking = sorted(required - cols)
        tables[name] = {"exists": exists, "columns": sorted(cols), "missing_required_columns": lacking}
        if not exists:
            missing.append(f"{DATABASE_SCHEMA}.{name} table is missing")
        elif lacking:
            missing.append(f"{DATABASE_SCHEMA}.{name} missing columns: {', '.join(lacking)}")

    template_cols = get_columns(cur, "templates") if table_exists(cur, "templates") else set()
    media_cols = get_columns(cur, "media_assets") if table_exists(cur, "media_assets") else set()
    migration_columns = {"audience_scope", "tier_id", "member_id", "media_asset_id", "is_media_template"}
    media_required = {"media_asset_id", "display_name", "original_filename", "mime_type", "message_type", "storage_path", "media_url", "file_size_bytes", "audience_scope", "tier_id", "member_id", "internal_note"}
    migration_missing = sorted(migration_columns - template_cols)
    media_missing = sorted(media_required - media_cols)
    migration_ready = not migration_missing and table_exists(cur, "media_assets") and not media_missing

    try:
        cur.execute("SELECT current_database() AS database_name, current_user AS database_user, current_schema() AS current_schema")
        identity = cur.fetchone()
    except Exception:
        identity = {"database_name": None, "database_user": None, "current_schema": None}

    live_log_ready = live_send_log_schema_ready(cur)
    live_blockers = live_send_configuration_issues()
    if not ALLOW_DB_WRITES:
        live_blockers.append("ALLOW_DB_WRITES is false; live sends require message logging.")
    if missing:
        live_blockers.append("The base Zyvefit database schema is not ready.")
    if not migration_ready:
        live_blockers.append("The media/template-scope migration is not ready.")
    if not live_log_ready:
        live_blockers.append("message_logs is missing required fields or does not allow standalone manual-send log rows.")
    database_name = (identity or {}).get("database_name")
    database_matches = (not LIVE_SENDS_REQUIRED_DATABASE) or (database_name == LIVE_SENDS_REQUIRED_DATABASE)
    if not database_matches:
        live_blockers.append(f"Live sends are restricted to database '{LIVE_SENDS_REQUIRED_DATABASE}', but this connection uses '{database_name or 'unknown'}'.")

    return {
        "database": identity,
        "schema": DATABASE_SCHEMA,
        "tables": tables,
        "read_ready": not missing,
        "missing_read_requirements": missing,
        "migration_ready": migration_ready,
        "migration_needed": (not migration_ready),
        "migration_missing_template_columns": migration_missing,
        "migration_missing_media_table_columns": media_missing,
        "writes_enabled_by_env": ALLOW_DB_WRITES,
        "writes_ready": ALLOW_DB_WRITES and not missing and migration_ready,
        "live_send_log_ready": live_log_ready,
        "live_send_required_database": LIVE_SENDS_REQUIRED_DATABASE,
        "live_send_database_match": database_matches,
        "live_send_blockers": live_blockers,
        "whatsapp_sending_enabled": not live_blockers,
    }


def require_write_ready() -> None:
    if not ALLOW_DB_WRITES:
        raise HTTPException(
            status_code=403,
            detail="Database writes are disabled. First verify read access, back up or clone your database, apply the reviewed SQL migration to the TEST database, then set ALLOW_DB_WRITES=true in .env.",
        )
    with db() as conn:
        status = inspect_schema(conn.cursor())
    if not status["read_ready"]:
        raise HTTPException(status_code=409, detail={"message": "The existing Zyvefit schema does not match this backend's expected columns.", "check": status})
    if not status["migration_ready"]:
        raise HTTPException(status_code=409, detail={"message": "The media/template-scope migration has not been applied to this database. Review sql/001_media_and_template_scope.sql and run it on the test database first.", "check": status})


def type_to_db(value: str) -> str:
    key = (value or "Text").strip().lower()
    if key not in TYPE_TO_DB:
        raise HTTPException(status_code=422, detail="Unsupported message type.")
    return TYPE_TO_DB[key]


def scope_fields(cur: psycopg.Cursor, scope: str, tier_name: str | None, member_id: str | None) -> tuple[str, int | None, int | None]:
    scope = (scope or "Shared").strip()
    if scope == "Shared":
        return "SHARED", None, None
    if scope in TIERS:
        cur.execute(sql.SQL("SELECT tier_id FROM {} WHERE tier_name=%s").format(qtable("tiers")), (scope,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=422, detail=f"Tier '{scope}' does not exist in the database.")
        return "TIER", int(row["tier_id"]), None
    if scope == "Member-specific":
        if not member_id:
            raise HTTPException(status_code=422, detail="Choose a member for member-specific content.")
        try:
            member_id_value = int(member_id)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="Invalid member ID.") from exc
        cur.execute(sql.SQL("SELECT member_id FROM {} WHERE member_id=%s AND is_active=TRUE").format(qtable("members")), (member_id_value,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=422, detail="That member was not found or is inactive.")
        return "MEMBER", None, int(row["member_id"])
    # Accept API-internal form for callers that submit a tier separately.
    if scope == "TIER" and tier_name:
        return scope_fields(cur, tier_name, None, None)
    raise HTTPException(status_code=422, detail="Audience scope must be Shared, a tier name, or Member-specific.")


def validate_media_url(value: str | None) -> str | None:
    url = (value or "").strip()
    if not url:
        return None
    if url.startswith("/uploads/") and ".." not in Path(url).parts and "\\" not in url:
        return url
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
        return url
    raise HTTPException(status_code=422, detail="Media URL must be HTTPS, or a local path beginning /uploads/.")


def map_template(row: dict[str, Any], tier_names: dict[str, str], member_names: dict[str, str]) -> dict[str, Any]:
    template_id = str(row["template_id"])
    db_scope = row.get("audience_scope") or "SHARED"
    if db_scope == "TIER":
        scope = tier_names.get(str(row.get("tier_id")), "Shared")
    elif db_scope == "MEMBER":
        scope = "Member-specific"
    else:
        scope = "Shared"
    media_url = row.get("media_url") or ""
    media_asset_id = row.get("media_asset_id")
    media_id = f"media-{media_asset_id}" if media_asset_id else (f"legacy-{template_id}" if media_url else "")
    return {
        "id": template_id,
        "code": row["template_code"],
        "name": row["template_name"],
        "type": TYPE_FROM_DB.get(str(row["message_type"]).upper(), "Document"),
        "scope": scope,
        "memberId": str(row["member_id"]) if row.get("member_id") is not None else "",
        "memberName": member_names.get(str(row.get("member_id")), ""),
        "language": row.get("language") or "en",
        "content": row.get("message_content") or "",
        "mediaUrl": media_url,
        "mediaId": media_id,
        "mediaName": Path(urlparse(media_url).path).name if media_url else "",
        "mediaType": TYPE_FROM_DB.get(str(row["message_type"]).upper(), "Document"),
        "updatedAt": (row.get("updated_at") or row.get("created_at")).isoformat() if (row.get("updated_at") or row.get("created_at")) else None,
        "isExample": False,
        "isMediaTemplate": bool(row.get("is_media_template", False)),
        "serverManaged": True,
    }


def lookup_maps(cur: psycopg.Cursor) -> tuple[dict[str, str], dict[str, str]]:
    tier_names: dict[str, str] = {}
    member_names: dict[str, str] = {}
    if table_exists(cur, "tiers"):
        cur.execute(sql.SQL("SELECT tier_id::text AS id, tier_name AS name FROM {} ").format(qtable("tiers")))
        tier_names = {row["id"]: row["name"] for row in cur.fetchall()}
    if table_exists(cur, "members"):
        cur.execute(sql.SQL("SELECT member_id::text AS id, member_name AS name FROM {} ").format(qtable("members")))
        member_names = {row["id"]: row["name"] for row in cur.fetchall()}
    return tier_names, member_names


def read_templates(cur: psycopg.Cursor) -> list[dict[str, Any]]:
    if not table_exists(cur, "templates"):
        raise HTTPException(status_code=409, detail=f"Table {DATABASE_SCHEMA}.templates was not found.")
    cols = get_columns(cur, "templates")
    required = {"template_id", "template_code", "template_name", "message_type", "message_content", "media_url", "language"}
    if not required.issubset(cols):
        raise HTTPException(status_code=409, detail="The templates table is missing required columns. Check /api/db/check.")
    has_scope = {"audience_scope", "tier_id", "member_id"}.issubset(cols)
    has_media = "media_asset_id" in cols
    has_source_flag = "is_media_template" in cols
    columns = ["template_id", "template_code", "template_name", "message_type", "message_content", "media_url", "language"]
    for col, default_sql in [
        ("audience_scope", "'SHARED'::text"), ("tier_id", "NULL::integer"), ("member_id", "NULL::integer"),
        ("media_asset_id", "NULL::bigint"), ("is_media_template", "FALSE"), ("created_at", "NULL::timestamp"), ("updated_at", "NULL::timestamp"),
    ]:
        columns.append(col if col in cols else f"{default_sql} AS {col}")
    cur.execute(sql.SQL("SELECT {} FROM {} ORDER BY template_id DESC").format(
        sql.SQL(", ").join(sql.Identifier(c) if c in cols else sql.SQL(c) for c in columns), qtable("templates")
    ))
    tier_names, member_names = lookup_maps(cur)
    return [map_template(row, tier_names, member_names) for row in cur.fetchall()]


def read_template_by_id(cur: psycopg.Cursor, template_id: int | str) -> dict[str, Any]:
    """Read one inserted/updated template by its database ID, without relying on list ordering."""
    cur.execute(
        sql.SQL("SELECT * FROM {} WHERE template_id=%s").format(qtable("templates")),
        (int(template_id),),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="The template was inserted but could not be read back.")
    tier_names, member_names = lookup_maps(cur)
    return map_template(row, tier_names, member_names)


def read_assets(cur: psycopg.Cursor) -> list[dict[str, Any]]:
    if not table_exists(cur, "media_assets"):
        return []
    cols = get_columns(cur, "media_assets")
    required = {"media_asset_id", "display_name", "original_filename", "mime_type", "message_type", "media_url", "file_size_bytes", "audience_scope", "tier_id", "member_id", "internal_note"}
    if not required.issubset(cols):
        return []
    cur.execute(sql.SQL("""
        SELECT media_asset_id, display_name, original_filename, mime_type, message_type,
               media_url, file_size_bytes, audience_scope, tier_id, member_id, internal_note, created_at, updated_at
        FROM {} ORDER BY media_asset_id DESC
    """).format(qtable("media_assets")))
    rows = cur.fetchall()
    tier_names, member_names = lookup_maps(cur)
    assets: list[dict[str, Any]] = []
    for row in rows:
        db_scope = row["audience_scope"]
        scope = tier_names.get(str(row["tier_id"]), "Shared") if db_scope == "TIER" else ("Member-specific" if db_scope == "MEMBER" else "Shared")
        media_url = row["media_url"]
        size_bytes = int(row["file_size_bytes"]) if row["file_size_bytes"] is not None else 0
        size_label = "Hosted media" if size_bytes == 0 else (f"{max(1, size_bytes // 1024)} KB" if size_bytes < 1024 * 1024 else f"{size_bytes / (1024 * 1024):.1f} MB")
        assets.append({
            "id": f"media-{row['media_asset_id']}", "serverAssetId": str(row["media_asset_id"]),
            "name": row["display_name"], "filename": row["original_filename"],
            "type": "PDF" if Path(row["original_filename"]).suffix.lower() == ".pdf" else TYPE_FROM_DB.get(str(row["message_type"]).upper(), "Document"),
            "scope": scope, "tier": tier_names.get(str(row["tier_id"]), "") if db_scope == "TIER" else "",
            "memberId": str(row["member_id"]) if row["member_id"] is not None else "",
            "memberName": member_names.get(str(row["member_id"]), ""), "description": row["internal_note"] or "",
            "sizeBytes": size_bytes or None, "size": size_label,
            "url": media_url, "previewUrl": media_url, "storageMode": "hosted",
            "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
            "serverManaged": True,
        })
    # Backward-compatible assets for old templates that have a media URL but are not in media_assets.
    cur.execute(sql.SQL("SELECT template_id, template_name, message_type, media_url FROM {} WHERE media_url IS NOT NULL AND media_url <> '' ORDER BY template_id DESC").format(qtable("templates")))
    seen_urls = {asset["url"] for asset in assets}
    for row in cur.fetchall():
        media_url = row["media_url"]
        if media_url in seen_urls:
            continue
        seen_urls.add(media_url)
        assets.append({
            "id": f"legacy-{row['template_id']}", "serverAssetId": "", "name": row["template_name"],
            "filename": Path(urlparse(media_url).path).name or row["template_name"],
            "type": "PDF" if urlparse(media_url).path.lower().endswith(".pdf") else TYPE_FROM_DB.get(str(row["message_type"]).upper(), "Document"),
            "scope": "Shared", "tier": "", "memberId": "", "memberName": "", "description": "Legacy media URL from an existing template",
            "size": "Hosted media", "url": media_url, "previewUrl": media_url, "storageMode": "hosted", "serverManaged": False,
        })
    return assets


def normalize_template_payload(payload: "TemplatePayload") -> dict[str, Any]:
    code = payload.code.strip().upper()
    name = payload.name.strip()
    content = payload.content.strip()
    if not code or not re.fullmatch(r"[A-Z0-9_]+", code):
        raise HTTPException(status_code=422, detail="Template code must contain uppercase letters, numbers, and underscores only.")
    if len(code) > 100 or not name or len(name) > 150:
        raise HTTPException(status_code=422, detail="Template code or name is empty or too long.")
    if len(content) > 4096:
        raise HTTPException(status_code=422, detail="Template content cannot exceed 4096 characters.")
    media_url = validate_media_url(payload.media_url)
    if not content and not media_url:
        raise HTTPException(status_code=422, detail="A template needs message content or an attached media URL.")
    return {"code": code, "name": name, "type": type_to_db(payload.type), "content": content,
            "language": payload.language.strip() or "en", "media_url": media_url,
            "scope": payload.scope, "tier": payload.tier, "member_id": payload.member_id,
            "media_asset_id": payload.media_asset_id}


class TemplatePayload(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    type: str = "Text"
    content: str = Field(default="", max_length=4096)
    language: str = Field(default="en", max_length=20)
    media_url: str | None = None
    media_asset_id: str | None = None
    scope: str = "Shared"
    tier: str | None = None
    member_id: str | None = None


class MediaMetadataPayload(BaseModel):
    name: str = Field(min_length=1, max_length=140)
    scope: str = "Shared"
    tier: str | None = None
    member_id: str | None = None
    description: str = Field(default="", max_length=500)


class MediaLinkPayload(MediaMetadataPayload):
    url: str = Field(min_length=1, max_length=2048)


class LiveSendPayload(BaseModel):
    audience_mode: Literal["member", "group"]
    member_id: str | None = None
    group_id: str | None = None
    message: str = Field(default="", max_length=4096)
    template_id: str | None = None
    media_asset_id: str | None = None
    media_url: str | None = None
    # Accepted for compatibility with the composer; the backend trusts the DB media type, not this field.
    media_type: str | None = None
    filename: str | None = Field(default=None, max_length=255)


def enforce_media_scope(cur: psycopg.Cursor, media_asset_id: int, template_scope: str, template_tier_id: int | None, template_member_id: int | None) -> None:
    cur.execute(sql.SQL("SELECT audience_scope, tier_id, member_id FROM {} WHERE media_asset_id=%s").format(qtable("media_assets")), (media_asset_id,))
    media = cur.fetchone()
    if not media:
        raise HTTPException(status_code=422, detail="Attached media was not found.")
    if media["audience_scope"] == "TIER" and (template_scope != "TIER" or template_tier_id != media["tier_id"]):
        raise HTTPException(status_code=422, detail="This media is tier-specific. The template must use the same tier or the media must be changed to Shared.")
    if media["audience_scope"] == "MEMBER" and (template_scope != "MEMBER" or template_member_id != media["member_id"]):
        raise HTTPException(status_code=422, detail="This media is member-specific. The template must target the same member or the media must be changed to Shared.")


def create_template_record(cur: psycopg.Cursor, data: dict[str, Any]) -> dict[str, Any]:
    db_scope, tier_id, member_id = scope_fields(cur, data["scope"], data.get("tier"), data.get("member_id"))
    media_asset_id = None
    if data.get("media_asset_id"):
        try:
            media_asset_id = int(data["media_asset_id"])
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="Invalid media asset ID.") from exc
        enforce_media_scope(cur, media_asset_id, db_scope, tier_id, member_id)
        cur.execute(sql.SQL("SELECT media_asset_id, media_url FROM {} WHERE media_asset_id=%s").format(qtable("media_assets")), (media_asset_id,))
        media = cur.fetchone()
        if not media:
            raise HTTPException(status_code=422, detail="Attached media was not found.")
        data["media_url"] = media["media_url"]
    cur.execute(sql.SQL("""
        INSERT INTO {} (template_code, template_name, message_type, message_content, media_url, language,
                        audience_scope, tier_id, member_id, media_asset_id, is_media_template)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE)
        RETURNING template_id
    """).format(qtable("templates")), (data["code"], data["name"], data["type"], data["content"], data["media_url"], data["language"], db_scope, tier_id, member_id, media_asset_id))
    return {"id": str(cur.fetchone()["template_id"])}


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, Any]:
    """Report the actual database connection used by this backend.

    Both /health and /api/health are supported during local setup.
    This endpoint only runs SELECT statements; it does not write to PostgreSQL.
    """
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 AS ok")
        cur.fetchone()
        cur.execute("""
            SELECT current_database() AS database_name,
                   current_user AS database_user,
                   current_schema() AS schema_name,
                   inet_server_addr()::text AS server_address,
                   inet_server_port() AS server_port
        """)
        identity = cur.fetchone()
        send_status = inspect_schema(cur)
    return {
        "status": "ok",
        "database_connected": True,
        "database": identity["database_name"],
        "database_user": identity["database_user"],
        "database_schema": identity["schema_name"],
        "server_address": identity["server_address"],
        "server_port": identity["server_port"],
        "schema_configured": DATABASE_SCHEMA,
        "mode": "local",
        "writes_enabled": ALLOW_DB_WRITES,
        "whatsapp_sending_enabled": bool(send_status["whatsapp_sending_enabled"]),
    }

@app.get("/api/db/check")
def database_check() -> dict[str, Any]:
    with db() as conn:
        return inspect_schema(conn.cursor())


# A deliberately narrow read-only database browser for local verification.
# Do not add phone_number, periskope_chat_id, credentials, or raw storage paths here.
DB_VIEW_TABLES: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("tiers", "Tiers", ("tier_id", "tier_name", "description", "created_at"), ("tier_id",)),
    ("phases", "Phases", ("phase_id", "phase_name", "phase_number", "start_day", "end_day", "description", "created_at"), ("phase_number", "phase_id")),
    ("members", "Members", ("member_id", "member_code", "member_name", "joining_date", "tier_id", "phase_id", "phase_override", "is_active", "created_at", "updated_at"), ("member_id",)),
    ("whatsapp_groups", "WhatsApp groups", ("group_id", "group_name", "created_at", "updated_at"), ("group_id",)),
    ("group_members", "Group members", ("group_id", "member_id", "joined_at", "left_at"), ("group_id", "member_id")),
    ("templates", "Templates", ("template_id", "template_code", "template_name", "message_type", "message_content", "media_url", "language", "audience_scope", "tier_id", "member_id", "media_asset_id", "is_media_template", "created_at", "updated_at"), ("template_id",)),
    ("media_assets", "Media assets", ("media_asset_id", "display_name", "original_filename", "mime_type", "message_type", "media_url", "file_size_bytes", "audience_scope", "tier_id", "member_id", "internal_note", "created_at", "updated_at"), ("media_asset_id",)),
    ("message_schedules", "Message schedules", ("schedule_id", "tier_id", "phase_id", "day_offset", "task_type", "template_id", "schedule_type", "send_time", "start_time", "end_time", "interval_minutes", "day_of_week", "day_of_month", "is_active", "created_at", "updated_at"), ("schedule_id",)),
    ("message_logs", "Message logs", ("message_log_id", "member_id", "group_id", "schedule_id", "template_id", "message_type", "status", "error_message", "scheduled_at", "sent_at", "created_at"), ("message_log_id",)),
    ("incoming_messages", "Incoming messages", ("incoming_message_id", "group_id", "member_id", "message_type", "message_content", "received_at"), ("incoming_message_id",)),
)


@app.get("/api/db/records")
def database_records() -> dict[str, Any]:
    """Return bounded, read-only samples and counts for known application tables."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT current_database() AS database_name, current_user AS database_user, current_schema() AS current_schema")
        identity = cur.fetchone()
        send_status = inspect_schema(cur)
        table_results: list[dict[str, Any]] = []
        for table_name, label, allowed_columns, preferred_order in DB_VIEW_TABLES:
            exists = table_exists(cur, table_name)
            if not exists:
                table_results.append({"name": table_name, "label": label, "exists": False, "row_count": 0, "displayed_rows": 0, "has_more": False, "columns": [], "rows": []})
                continue
            actual_columns = get_columns(cur, table_name)
            selected_columns = [column for column in allowed_columns if column in actual_columns]
            cur.execute(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(qtable(table_name)))
            row_count = int(cur.fetchone()["n"])
            rows: list[dict[str, Any]] = []
            if selected_columns:
                order_columns = [column for column in preferred_order if column in selected_columns]
                query = sql.SQL("SELECT {} FROM {}").format(
                    sql.SQL(", ").join(sql.Identifier(column) for column in selected_columns),
                    qtable(table_name),
                )
                if order_columns:
                    query += sql.SQL(" ORDER BY {} DESC").format(sql.SQL(", ").join(sql.Identifier(column) for column in order_columns))
                query += sql.SQL(" LIMIT 100")
                cur.execute(query)
                rows = cur.fetchall()
            table_results.append({
                "name": table_name,
                "label": label,
                "exists": True,
                "row_count": row_count,
                "displayed_rows": len(rows),
                "has_more": row_count > len(rows),
                "columns": selected_columns,
                "rows": rows,
            })
    # Normalize date/time/Decimal and other supported DB types for browser JSON.
    return jsonable_encoder({
        "database": identity,
        "schema": DATABASE_SCHEMA,
        "read_only_view": True,
        "whatsapp_sending_enabled": bool(send_status["whatsapp_sending_enabled"]),
        "tables": table_results,
    })


@app.get("/api/bootstrap")
def bootstrap() -> dict[str, Any]:
    with db() as conn:
        cur = conn.cursor()
        status = inspect_schema(cur)
        tiers = []
        phases = []
        members = []
        groups = []
        if table_exists(cur, "tiers"):
            cur.execute(sql.SQL("SELECT tier_id::text AS id, tier_name AS name FROM {} ORDER BY tier_name").format(qtable("tiers")))
            tiers = cur.fetchall()
        if table_exists(cur, "phases"):
            cur.execute(sql.SQL("SELECT phase_id::text AS id, phase_name AS name, phase_number, start_day, end_day FROM {} ORDER BY phase_number").format(qtable("phases")))
            phases = cur.fetchall()
        if table_exists(cur, "members"):
            members_cols = get_columns(cur, "members")
            required = {"member_id", "member_code", "member_name", "tier_id", "phase_id", "is_active"}
            if required.issubset(members_cols):
                cur.execute(sql.SQL("""
                  SELECT m.member_id::text AS id, m.member_code AS code, m.member_name AS name,
                         t.tier_name AS tier, p.phase_name AS phase
                  FROM {} m LEFT JOIN {} t ON t.tier_id=m.tier_id
                  LEFT JOIN {} p ON p.phase_id=m.phase_id
                  WHERE m.is_active=TRUE ORDER BY m.member_name LIMIT 1000
                """).format(qtable("members"), qtable("tiers"), qtable("phases")))
                members = cur.fetchall()
        if table_exists(cur, "whatsapp_groups"):
            if table_exists(cur, "group_members"):
                gm_cols = get_columns(cur, "group_members")
                if {"group_id", "member_id"}.issubset(gm_cols):
                    active_clause = " AND gm.left_at IS NULL" if "left_at" in gm_cols else ""
                    cur.execute(sql.SQL("""
                      SELECT g.group_id::text AS id, g.group_name AS name,
                             COALESCE(array_agg(gm.member_id::text) FILTER (WHERE gm.member_id IS NOT NULL), ARRAY[]::text[]) AS members
                      FROM {} g LEFT JOIN {} gm ON gm.group_id=g.group_id {active_clause}
                      GROUP BY g.group_id, g.group_name ORDER BY g.group_name
                    """).format(qtable("whatsapp_groups"), qtable("group_members"), active_clause=sql.SQL(active_clause)))
                    groups = cur.fetchall()
            else:
                cur.execute(sql.SQL("SELECT group_id::text AS id, group_name AS name, ARRAY[]::text[] AS members FROM {} ORDER BY group_name").format(qtable("whatsapp_groups")))
                groups = cur.fetchall()
        templates = read_templates(cur) if table_exists(cur, "templates") else []
        assets = read_assets(cur)
    # JSON's standard encoder does not handle UUID/date/Decimal automatically, but all returned values above are serializable.
    return {"database": status, "writes_enabled": bool(status["writes_ready"]),
            "whatsapp_sending_enabled": bool(status["whatsapp_sending_enabled"]), "tiers": tiers, "phases": phases, "members": members,
            "groups": groups, "templates": templates, "assets": assets}


@app.get("/api/templates")
def list_templates() -> list[dict[str, Any]]:
    with db() as conn:
        return read_templates(conn.cursor())


@app.post("/api/templates")
def add_template(payload: TemplatePayload) -> dict[str, Any]:
    require_write_ready()
    data = normalize_template_payload(payload)
    try:
        with db() as conn:
            cur = conn.cursor()
            created = create_template_record(cur, data)
            return read_template_by_id(cur, created["id"])
    except errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="A template with this code already exists.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Template create failed")
        raise HTTPException(status_code=500, detail="Could not save template. Check backend logs for the database error.") from exc


@app.put("/api/templates/{template_id}")
def update_template(template_id: int, payload: TemplatePayload) -> dict[str, Any]:
    require_write_ready()
    data = normalize_template_payload(payload)
    try:
        with db() as conn:
            cur = conn.cursor()
            cur.execute(sql.SQL("SELECT is_media_template, media_asset_id FROM {} WHERE template_id=%s").format(qtable("templates")), (template_id,))
            current = cur.fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="Template not found.")
            db_scope, tier_id, member_id = scope_fields(cur, data["scope"], data.get("tier"), data.get("member_id"))
            media_asset_id = None
            if data.get("media_asset_id"):
                try:
                    media_asset_id = int(data["media_asset_id"])
                except (ValueError, TypeError) as exc:
                    raise HTTPException(status_code=422, detail="Invalid media asset ID.") from exc
                if not current["is_media_template"]:
                    enforce_media_scope(cur, media_asset_id, db_scope, tier_id, member_id)
                cur.execute(sql.SQL("SELECT media_url FROM {} WHERE media_asset_id=%s").format(qtable("media_assets")), (media_asset_id,))
                media = cur.fetchone()
                if not media:
                    raise HTTPException(status_code=422, detail="Attached media was not found.")
                data["media_url"] = media["media_url"]
            if current["is_media_template"]:
                # Media-upload templates remain attached to their original media asset.
                media_asset_id = int(current["media_asset_id"])
                cur.execute(sql.SQL("SELECT media_url FROM {} WHERE media_asset_id=%s").format(qtable("media_assets")), (media_asset_id,))
                media_row = cur.fetchone()
                if not media_row:
                    raise HTTPException(status_code=409, detail="The media asset linked to this template is missing.")
                data["media_url"] = media_row["media_url"]
            cur.execute(sql.SQL("""
              UPDATE {} SET template_code=%s, template_name=%s, message_type=%s, message_content=%s,
                media_url=%s, language=%s, audience_scope=%s, tier_id=%s, member_id=%s, media_asset_id=%s,
                updated_at=CURRENT_TIMESTAMP
              WHERE template_id=%s
              RETURNING template_id
            """).format(qtable("templates")), (data["code"], data["name"], data["type"], data["content"], data["media_url"], data["language"], db_scope, tier_id, member_id, media_asset_id, template_id))
            cur.fetchone()
            if current["is_media_template"]:
                cur.execute(sql.SQL("""
                  UPDATE {} SET display_name=%s, message_type=%s, audience_scope=%s, tier_id=%s, member_id=%s,
                                 updated_at=CURRENT_TIMESTAMP
                  WHERE media_asset_id=%s
                """).format(qtable("media_assets")), (data["name"], data["type"], db_scope, tier_id, member_id, media_asset_id))
            items = read_templates(cur)
            return next(item for item in items if item["id"] == str(template_id))
    except errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="A template with this code already exists.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Template update failed")
        raise HTTPException(status_code=500, detail="Could not update template. Check backend logs for the database error.") from exc


@app.delete("/api/templates/{template_id}")
def remove_template(template_id: int) -> dict[str, Any]:
    require_write_ready()
    try:
        with db() as conn:
            cur = conn.cursor()
            if table_exists(cur, "message_schedules"):
                cur.execute(sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE template_id=%s").format(qtable("message_schedules")), (template_id,))
                if cur.fetchone()["n"]:
                    raise HTTPException(status_code=409, detail="This template is referenced by a message schedule; deactivate/update that schedule before deleting it.")
            if table_exists(cur, "message_logs"):
                cur.execute(sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE template_id=%s").format(qtable("message_logs")), (template_id,))
                if cur.fetchone()["n"]:
                    raise HTTPException(status_code=409, detail="This template appears in message logs and cannot be deleted through this console.")
            cur.execute(sql.SQL("DELETE FROM {} WHERE template_id=%s AND is_media_template=FALSE RETURNING template_id").format(qtable("templates")), (template_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Template not found, or it is managed from the Media Library.")
        return {"deleted": True, "template_id": str(template_id)}
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Template delete failed")
        raise HTTPException(status_code=500, detail="Could not delete template. Check backend logs for the database error.") from exc


def validate_scope_before_upload(cur: psycopg.Cursor, scope: str, tier: str | None, member_id: str | None) -> tuple[str, int | None, int | None]:
    return scope_fields(cur, scope, tier, member_id)


def filename_info(original_filename: str, content_type: str | None) -> tuple[str, str]:
    filename = Path(original_filename or "upload").name.replace("\x00", "")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"File type '{suffix or '(no extension)'}' is not allowed.")
    mime = (content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream").lower()
    # Refuse active web content even if the filename is misleading.
    if mime in {"text/html", "application/xhtml+xml", "image/svg+xml", "application/javascript", "text/javascript"}:
        raise HTTPException(status_code=415, detail="This file content type is not allowed.")
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        message_type = "IMAGE"
    elif suffix in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus"}:
        message_type = "AUDIO"
    elif suffix in {".mp4", ".mov", ".webm", ".m4v"}:
        message_type = "VIDEO"
    else:
        message_type = "DOCUMENT"
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(filename).stem).strip(" ._") or "uploaded_media"
    safe_suffix = re.sub(r"[^A-Za-z0-9.]", "", suffix)
    return f"{safe_stem[:120]}{safe_suffix}", message_type


def unique_template_code(cur: psycopg.Cursor, prefix: str = "UPLOAD") -> str:
    for _ in range(5):
        code = f"{prefix}_{uuid.uuid4().hex[:16].upper()}"
        cur.execute(sql.SQL("SELECT 1 FROM {} WHERE template_code=%s").format(qtable("templates")), (code,))
        if not cur.fetchone():
            return code
    raise HTTPException(status_code=500, detail="Could not generate a unique template code.")


@app.post("/api/media")
def upload_media(
    file: UploadFile = File(...),
    name: str = Form(""),
    scope: str = Form("Shared"),
    tier: str = Form(""),
    member_id: str = Form(""),
    description: str = Form(""),
    create_template: bool = Form(True),
) -> dict[str, Any]:
    require_write_ready()
    if not file.filename:
        raise HTTPException(status_code=422, detail="Choose a file to upload.")
    clean_filename, message_type = filename_info(file.filename, file.content_type)
    ext = Path(clean_filename).suffix.lower()
    token = uuid.uuid4().hex
    stored_filename = f"{token}_{clean_filename}"
    destination = UPLOAD_DIR / stored_filename
    public_path = f"/uploads/{stored_filename}"
    size = 0
    try:
        with destination.open("xb") as target:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"Files must be {MAX_UPLOAD_MB} MB or smaller.")
                target.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="The uploaded file is empty.")
        display_name = (name or Path(clean_filename).stem).strip()[:140]
        if not display_name:
            display_name = Path(clean_filename).stem[:140] or "Uploaded media"
        note = (description or "").strip()[:500]
        with db() as conn:
            cur = conn.cursor()
            db_scope, tier_id, resolved_member_id = validate_scope_before_upload(cur, scope, tier or None, member_id or None)
            cur.execute(sql.SQL("""
                INSERT INTO {} (display_name, original_filename, mime_type, message_type, storage_path, media_url,
                                file_size_bytes, audience_scope, tier_id, member_id, internal_note)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING media_asset_id
            """).format(qtable("media_assets")), (display_name, clean_filename, file.content_type or mimetypes.guess_type(clean_filename)[0] or "application/octet-stream", message_type, str(destination), public_path, size, db_scope, tier_id, resolved_member_id, note))
            media_id = int(cur.fetchone()["media_asset_id"])
            template = None
            if create_template:
                code = unique_template_code(cur)
                default_caption = f"Please review the attached resource: {display_name}."
                cur.execute(sql.SQL("""
                    INSERT INTO {} (template_code, template_name, message_type, message_content, media_url, language,
                                    audience_scope, tier_id, member_id, media_asset_id, is_media_template)
                    VALUES (%s,%s,%s,%s,%s,'en',%s,%s,%s,%s,TRUE)
                    RETURNING template_id
                """).format(qtable("templates")), (code, display_name, message_type, default_caption, public_path, db_scope, tier_id, resolved_member_id, media_id))
                template_id = cur.fetchone()["template_id"]
                template = read_template_by_id(cur, template_id)
                template["mediaId"] = f"media-{media_id}"
                template["mediaUrl"] = public_path
                template["mediaName"] = display_name
        asset = {
            "id": f"media-{media_id}", "serverAssetId": str(media_id), "name": display_name,
            "filename": clean_filename, "type": "PDF" if ext == ".pdf" else TYPE_FROM_DB[message_type],
            "scope": scope if scope != "TIER" else (tier or "Shared"), "tier": tier if db_scope == "TIER" else "",
            "memberId": resolved_member_id and str(resolved_member_id) or "", "description": note,
            "sizeBytes": size, "size": f"{max(1, size // 1024)} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB",
            "url": public_path, "previewUrl": public_path, "storageMode": "hosted", "createdAt": None,
            "serverManaged": True,
        }
        return {"asset": asset, "template": template, "whatsapp_sending_enabled": False}
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except errors.UniqueViolation as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="A duplicate record prevented this upload from being saved. Try again.") from exc
    except Exception as exc:
        destination.unlink(missing_ok=True)
        log.exception("Media upload failed")
        raise HTTPException(status_code=500, detail="Upload could not be saved. Check backend logs; no WhatsApp message was sent.") from exc
    finally:
        file.file.close()


@app.post("/api/media/link")
def register_media_link(payload: MediaLinkPayload) -> dict[str, Any]:
    """Register a hosted URL and automatically create a media template for it."""
    require_write_ready()
    media_url = validate_media_url(payload.url)
    if not media_url or not media_url.startswith("https://"):
        raise HTTPException(status_code=422, detail="For a hosted media link, provide an HTTPS URL.")
    suffix = Path(urlparse(media_url).path).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="The hosted URL must end in a supported file extension.")
    mime = mimetypes.guess_type(urlparse(media_url).path)[0] or "application/octet-stream"
    _, message_type = filename_info(f"linked{suffix}", mime)
    require_write_ready()
    with db() as conn:
        cur = conn.cursor()
        db_scope, tier_id, member_id = validate_scope_before_upload(cur, payload.scope, payload.tier, payload.member_id)
        name = payload.name.strip()
        cur.execute(sql.SQL("""
          INSERT INTO {} (display_name, original_filename, mime_type, message_type, storage_path, media_url,
                          file_size_bytes, audience_scope, tier_id, member_id, internal_note)
          VALUES (%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s) RETURNING media_asset_id
        """).format(qtable("media_assets")), (name, Path(urlparse(media_url).path).name[:255], mime, message_type, "HOSTED:" + media_url, media_url, db_scope, tier_id, member_id, payload.description.strip()))
        media_id = int(cur.fetchone()["media_asset_id"])
        code = unique_template_code(cur)
        content = f"Please review the attached resource: {name}."
        cur.execute(sql.SQL("""
          INSERT INTO {} (template_code, template_name, message_type, message_content, media_url, language,
                          audience_scope, tier_id, member_id, media_asset_id, is_media_template)
          VALUES (%s,%s,%s,%s,%s,'en',%s,%s,%s,%s,TRUE) RETURNING template_id
        """).format(qtable("templates")), (code, name, message_type, content, media_url, db_scope, tier_id, member_id, media_id))
        template_id = str(cur.fetchone()["template_id"])
        items = read_templates(cur)
        template = next(item for item in items if item["id"] == template_id)
        template["mediaId"] = f"media-{media_id}"
        asset = {"id": f"media-{media_id}", "serverAssetId": str(media_id), "name": name,
                 "filename": Path(urlparse(media_url).path).name, "type": "PDF" if suffix == ".pdf" else TYPE_FROM_DB[message_type],
                 "scope": payload.scope, "tier": payload.tier or "", "memberId": member_id and str(member_id) or "",
                 "memberName": "", "description": payload.description, "size": "Hosted media", "url": media_url,
                 "previewUrl": media_url, "storageMode": "hosted", "serverManaged": True}
        return {"asset": asset, "template": template, "whatsapp_sending_enabled": False}


@app.put("/api/media/{media_asset_id}")
def update_media(media_asset_id: int, payload: MediaMetadataPayload) -> dict[str, Any]:
    require_write_ready()
    with db() as conn:
        cur = conn.cursor()
        db_scope, tier_id, member_id = validate_scope_before_upload(cur, payload.scope, payload.tier, payload.member_id)
        cur.execute(sql.SQL("""
          UPDATE {} SET display_name=%s, audience_scope=%s, tier_id=%s, member_id=%s, internal_note=%s,
                         updated_at=CURRENT_TIMESTAMP
          WHERE media_asset_id=%s RETURNING media_asset_id, media_url, message_type
        """).format(qtable("media_assets")), (payload.name.strip(), db_scope, tier_id, member_id, payload.description.strip(), media_asset_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Media asset not found.")
        # Keep the upload-generated template aligned with the media library's scope/name.
        cur.execute(sql.SQL("""
          UPDATE {} SET template_name=%s, audience_scope=%s, tier_id=%s, member_id=%s, updated_at=CURRENT_TIMESTAMP
          WHERE media_asset_id=%s AND is_media_template=TRUE
        """).format(qtable("templates")), (payload.name.strip(), db_scope, tier_id, member_id, media_asset_id))
    return {"id": f"media-{media_asset_id}", "name": payload.name.strip(), "scope": payload.scope,
            "tier": payload.tier or "", "memberId": member_id and str(member_id) or "", "description": payload.description,
            "url": row["media_url"], "previewUrl": row["media_url"], "storageMode": "hosted", "serverManaged": True}


@app.delete("/api/media/{media_asset_id}")
def remove_media(media_asset_id: int) -> dict[str, Any]:
    require_write_ready()
    stored_path: str | None = None
    with db() as conn:
        cur = conn.cursor()
        cur.execute(sql.SQL("SELECT storage_path FROM {} WHERE media_asset_id=%s").format(qtable("media_assets")), (media_asset_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Media asset not found.")
        stored_path = row["storage_path"]
        cur.execute(sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE media_asset_id=%s AND is_media_template=FALSE").format(qtable("templates")), (media_asset_id,))
        if cur.fetchone()["n"]:
            raise HTTPException(status_code=409, detail="This media is attached to another template. Remove those references before deleting it.")
        cur.execute(sql.SQL("SELECT template_id FROM {} WHERE media_asset_id=%s AND is_media_template=TRUE").format(qtable("templates")), (media_asset_id,))
        source_template = cur.fetchone()
        if source_template:
            template_id = source_template["template_id"]
            if table_exists(cur, "message_schedules"):
                cur.execute(sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE template_id=%s").format(qtable("message_schedules")), (template_id,))
                if cur.fetchone()["n"]:
                    raise HTTPException(status_code=409, detail="This uploaded template is used by a schedule and cannot be deleted.")
            if table_exists(cur, "message_logs"):
                cur.execute(sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE template_id=%s").format(qtable("message_logs")), (template_id,))
                if cur.fetchone()["n"]:
                    raise HTTPException(status_code=409, detail="This uploaded template appears in message logs and cannot be deleted.")
            cur.execute(sql.SQL("DELETE FROM {} WHERE template_id=%s").format(qtable("templates")), (template_id,))
        cur.execute(sql.SQL("DELETE FROM {} WHERE media_asset_id=%s").format(qtable("media_assets")), (media_asset_id,))
    if stored_path and not stored_path.startswith("HOSTED:"):
        path = Path(stored_path).resolve()
        if UPLOAD_DIR.resolve() in path.parents:
            path.unlink(missing_ok=True)
    return {"deleted": True, "media_asset_id": str(media_asset_id)}


def _render_live_message(message: str, variables: dict[str, str]) -> str:
    """Resolve supported template tokens for one member or one group; reject unknown tokens."""
    unresolved: list[str] = []
    token_pattern = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

    def replace(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        if key not in variables:
            unresolved.append(match.group(0))
            return match.group(0)
        return variables[key]

    rendered = token_pattern.sub(replace, message)
    if unresolved or re.search(r"\{\{\s*[^{}]+\s*\}\}", rendered):
        tokens = ", ".join(dict.fromkeys(unresolved)) or "unknown token"
        raise HTTPException(status_code=422, detail=f"Unsupported/unresolved template placeholder(s): {tokens}. Replace them before sending.")
    return rendered


def _enforce_manual_scope(scope: str | None, scoped_tier_id: int | None, scoped_member_id: int | None,
                         audience_mode: Literal["member", "group"], member_id: int | None,
                         member_tier_id: int | None, label: str) -> None:
    scope_value = str(scope or "SHARED").upper()
    if scope_value == "MEMBER":
        if audience_mode != "member" or member_id is None or int(scoped_member_id or 0) != member_id:
            raise HTTPException(status_code=422, detail=f"{label} is member-specific and does not belong to the selected member.")
    elif scope_value == "TIER":
        if audience_mode != "member" or member_tier_id is None or int(scoped_tier_id or 0) != member_tier_id:
            raise HTTPException(status_code=422, detail=f"{label} is tier-specific; it can only be sent to one member in that same tier, not to a group or a member in another tier.")
    elif scope_value not in {"SHARED", ""}:
        raise HTTPException(status_code=422, detail=f"{label} has an unsupported audience scope.")


def _registered_media_for_send(cur: psycopg.Cursor, payload: LiveSendPayload,
                               member_id: int | None, member_tier_id: int | None,
                               audience_mode: Literal["member", "group"],
                               media_url: str) -> tuple[str, str]:
    """Use only a media URL already registered in media_assets or templates."""
    supplied_url = (media_url or "").strip()
    asset_row: dict[str, Any] | None = None

    if payload.media_asset_id:
        try:
            asset_id = int(payload.media_asset_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Invalid media asset ID.") from exc
        cur.execute(sql.SQL("SELECT media_asset_id, media_url, message_type, audience_scope, tier_id, member_id FROM {} WHERE media_asset_id=%s")
                    .format(qtable("media_assets")), (asset_id,))
        asset_row = cur.fetchone()
        if not asset_row:
            raise HTTPException(status_code=404, detail="The selected media asset was not found in PostgreSQL.")
        stored_url = str(asset_row.get("media_url") or "").strip()
        if supplied_url and supplied_url != stored_url:
            raise HTTPException(status_code=422, detail="The selected media URL does not match the stored media asset.")
        supplied_url = stored_url

    validated = validate_media_url(supplied_url)
    if not validated or not validated.lower().startswith("https://"):
        raise HTTPException(status_code=422, detail="Live media needs a publicly reachable HTTPS URL. Files stored on your Mac at /uploads/... cannot be fetched by Periskope.")
    parsed = urlparse(validated)
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise HTTPException(status_code=422, detail="Live media needs a public HTTPS URL; local hosts cannot be fetched by Periskope.")

    if asset_row is None:
        cur.execute(sql.SQL("SELECT media_asset_id, media_url, message_type, audience_scope, tier_id, member_id FROM {} WHERE media_url=%s ORDER BY media_asset_id DESC LIMIT 1")
                    .format(qtable("media_assets")), (validated,))
        asset_row = cur.fetchone()

    if asset_row:
        if str(asset_row.get("media_url") or "") != validated:
            raise HTTPException(status_code=422, detail="The selected media URL does not match the stored media asset.")
        _enforce_manual_scope(asset_row.get("audience_scope"), asset_row.get("tier_id"), asset_row.get("member_id"),
                              audience_mode, member_id, member_tier_id, "The selected media")
        message_type = str(asset_row.get("message_type") or "DOCUMENT").upper()
    else:
        cur.execute(sql.SQL("SELECT message_type, audience_scope, tier_id, member_id, media_url FROM {} WHERE media_url=%s ORDER BY template_id DESC LIMIT 1")
                    .format(qtable("templates")), (validated,))
        template_media = cur.fetchone()
        if not template_media:
            raise HTTPException(status_code=422, detail="Only media already registered in Media Library or a saved template can be sent.")
        _enforce_manual_scope(template_media.get("audience_scope"), template_media.get("tier_id"), template_media.get("member_id"),
                              audience_mode, member_id, member_tier_id, "The selected template media")
        message_type = str(template_media.get("message_type") or "DOCUMENT").upper()

    if message_type not in {"IMAGE", "VIDEO", "AUDIO", "DOCUMENT"}:
        raise HTTPException(status_code=422, detail=f"The selected media is stored as {message_type}; live sending supports images, video, audio, and documents only.")
    return message_type, validated


def _start_manual_send_log(cur: psycopg.Cursor, member_id: int | None, group_id: int | None,
                           template_id: int | None, message_type: str, message: str,
                           media_url: str | None) -> int:
    if not live_send_log_schema_ready(cur):
        raise HTTPException(status_code=409, detail="message_logs is missing required fields or cannot store a standalone manual-send log. No Periskope request was made.")
    cols = get_columns(cur, "message_logs")
    values: dict[str, Any] = {
        "member_id": member_id,
        "group_id": group_id,
        "schedule_id": None,
        "template_id": template_id,
        "message_type": message_type,
        "message_content": message,
        "media_url": media_url,
        "status": "PENDING",
        "error_message": None,
        "periskope_message_id": None,
    }
    cols_to_write = [name for name in values if name in cols]
    columns = [*cols_to_write, "scheduled_at", "created_at"]
    expressions = [sql.Placeholder() for _ in cols_to_write] + [sql.SQL("CURRENT_TIMESTAMP"), sql.SQL("CURRENT_TIMESTAMP")]
    cur.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING message_log_id").format(
            qtable("message_logs"),
            sql.SQL(", ").join(sql.Identifier(name) for name in columns),
            sql.SQL(", ").join(expressions),
        ),
        [values[name] for name in cols_to_write],
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="Could not create the message audit log. No Periskope request was made.")
    return int(row["message_log_id"])


def _finish_manual_send_log(message_log_id: int, status: str, error_message: str | None = None,
                            provider_message_id: str | None = None) -> None:
    with db() as conn:
        cur = conn.cursor()
        cols = get_columns(cur, "message_logs")
        values: dict[str, Any] = {"status": status}
        if "error_message" in cols:
            values["error_message"] = (error_message or "")[:3500] or None
        if "periskope_message_id" in cols:
            values["periskope_message_id"] = provider_message_id
        assignments = [sql.SQL("{}=%s").format(sql.Identifier(name)) for name in values if name in cols]
        params = [values[name] for name in values if name in cols]
        if "sent_at" in cols:
            if status in {"SENT", "DELIVERED", "READ"}:
                assignments.append(sql.SQL("sent_at=CURRENT_TIMESTAMP"))
            else:
                assignments.append(sql.SQL("sent_at=NULL"))
        cur.execute(
            sql.SQL("UPDATE {} SET {} WHERE message_log_id=%s").format(qtable("message_logs"), sql.SQL(", ").join(assignments)),
            [*params, message_log_id],
        )


@app.post("/api/send", status_code=202)
def send_live_message(payload: LiveSendPayload) -> dict[str, Any]:
    """Manually send one allowlisted member/group message using the existing scheduler adapter."""
    config_issues = live_send_configuration_issues()
    if config_issues:
        raise HTTPException(status_code=403, detail="Live sends are not enabled: " + " ".join(config_issues))
    if not ALLOW_DB_WRITES:
        raise HTTPException(status_code=403, detail="ALLOW_DB_WRITES must be true so every live attempt can be logged. No message was sent.")
    if payload.audience_mode == "member" and not payload.member_id:
        raise HTTPException(status_code=422, detail="Select one member before sending.")
    if payload.audience_mode == "group" and not payload.group_id:
        raise HTTPException(status_code=422, detail="Select one WhatsApp group before sending.")
    if payload.audience_mode == "member" and payload.group_id:
        raise HTTPException(status_code=422, detail="Choose exactly one recipient: a member or a group.")
    if payload.audience_mode == "group" and payload.member_id:
        raise HTTPException(status_code=422, detail="Choose exactly one recipient: a member or a group.")

    # Create the existing Periskope client before a log row or send attempt. This constructor
    # must not send a message; the first external send call occurs only after audit logging.
    try:
        from periskope_adapter import build_client, send_message
        client = build_client()
    except Exception as exc:
        log.exception("Could not initialize the existing Periskope adapter; no send was attempted")
        raise HTTPException(status_code=503, detail="Could not initialize the existing Periskope adapter. Ensure periskope_adapter.py and Periskope.py are importable and the .env credentials are set. No message was sent.") from exc

    message = (payload.message or "").strip()
    media_url = (payload.media_url or "").strip()
    message_log_id: int | None = None
    target_chat_id = ""
    recipient_name = ""
    member_db_id: int | None = None
    group_db_id: int | None = None
    member_tier_id: int | None = None
    variables: dict[str, str] = {}
    message_type = "TEXT"
    template_id_value: int | None = None

    if payload.template_id:
        try:
            template_id_value = int(payload.template_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Invalid template ID. Refresh templates and choose a database-backed template.") from exc

    try:
        with db() as conn:
            cur = conn.cursor()
            schema_status = inspect_schema(cur)
            if not schema_status.get("whatsapp_sending_enabled"):
                blockers = schema_status.get("live_send_blockers") or []
                detail = "Live sends are blocked by backend/database readiness checks."
                if blockers:
                    detail += " " + " ".join(str(item) for item in blockers)
                raise HTTPException(status_code=409, detail=detail)

            template_row: dict[str, Any] | None = None
            if template_id_value is not None:
                cur.execute(sql.SQL("SELECT * FROM {} WHERE template_id=%s").format(qtable("templates")), (template_id_value,))
                template_row = cur.fetchone()
                if not template_row:
                    raise HTTPException(status_code=404, detail="The selected template was not found in PostgreSQL.")

            if payload.audience_mode == "member":
                try:
                    member_db_id = int(payload.member_id or "")
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=422, detail="Invalid member ID.") from exc
                member_cols = get_columns(cur, "members")
                target_cols = [name for name in ("whatsapp_sender_id", "phone_number") if name in member_cols]
                if not target_cols:
                    raise HTTPException(status_code=409, detail="members needs whatsapp_sender_id or phone_number before direct member sends can be used.")
                select_cols = ["m.member_id", "m.member_name", "m.member_code", "m.tier_id", "m.phase_id", "t.tier_name", "ph.phase_name", *[f"m.{name}" for name in target_cols]]
                cur.execute(
                    sql.SQL("SELECT {} FROM {} m LEFT JOIN {} t ON t.tier_id=m.tier_id LEFT JOIN {} ph ON ph.phase_id=m.phase_id WHERE m.member_id=%s AND m.is_active=TRUE").format(
                        sql.SQL(", ").join(sql.SQL(name) for name in select_cols),
                        qtable("members"), qtable("tiers"), qtable("phases"),
                    ),
                    (member_db_id,),
                )
                member_row = cur.fetchone()
                if not member_row:
                    raise HTTPException(status_code=404, detail="The selected member was not found or is inactive.")
                member_tier_id = int(member_row["tier_id"]) if member_row.get("tier_id") is not None else None
                recipient_name = str(member_row.get("member_name") or "Selected member")
                raw_id = str(member_row.get("whatsapp_sender_id") or member_row.get("phone_number") or "")
                target_chat_id = normalize_live_chat_id(raw_id, "member")
                variables = {
                    "member_name": recipient_name,
                    "first_name": recipient_name.split()[0] if recipient_name.split() else recipient_name,
                    "member_code": str(member_row.get("member_code") or ""),
                    "tier_name": str(member_row.get("tier_name") or ""),
                    "phase_name": str(member_row.get("phase_name") or ""),
                    "group_name": "",
                }
            else:
                try:
                    group_db_id = int(payload.group_id or "")
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=422, detail="Invalid WhatsApp group ID.") from exc
                cur.execute(sql.SQL("SELECT group_id, group_name, periskope_chat_id FROM {} WHERE group_id=%s").format(qtable("whatsapp_groups")), (group_db_id,))
                group_row = cur.fetchone()
                if not group_row:
                    raise HTTPException(status_code=404, detail="The selected WhatsApp group was not found.")
                recipient_name = str(group_row.get("group_name") or "Selected group")
                target_chat_id = normalize_live_chat_id(str(group_row.get("periskope_chat_id") or ""), "group")
                variables = {"group_name": recipient_name}

            if target_chat_id not in allowed_live_chat_ids():
                raise HTTPException(status_code=403, detail=f"'{recipient_name}' is not in WHATSAPP_ALLOWED_CHAT_IDS. No message was sent.")

            if template_row:
                _enforce_manual_scope(template_row.get("audience_scope"), template_row.get("tier_id"), template_row.get("member_id"),
                                      payload.audience_mode, member_db_id, member_tier_id, "The selected template")
                if not media_url and not payload.media_asset_id and str(template_row.get("message_type") or "TEXT").upper() != "TEXT":
                    raise HTTPException(status_code=422, detail="The selected template requires media. Attach its media asset explicitly before sending.")

            if media_url or payload.media_asset_id:
                message_type, media_url = _registered_media_for_send(
                    cur, payload, member_db_id, member_tier_id, payload.audience_mode, media_url
                )
            else:
                message_type = "TEXT"

            if message_type == "LOCATION":
                raise HTTPException(status_code=422, detail="The existing Periskope adapter does not implement location sends.")
            if not message and not media_url:
                raise HTTPException(status_code=422, detail="Write a text message or attach registered media before sending.")
            message = _render_live_message(message, variables)

            message_log_id = _start_manual_send_log(
                cur, member_db_id, group_db_id, template_id_value, message_type, message, media_url
            )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Could not prepare the logged live-send request; no Periskope request was made")
        raise HTTPException(status_code=500, detail="Could not validate the recipient or create the audit log. No Periskope request was made; check backend logs.") from exc

    # No automatic retries: if this call raises, the provider may still have accepted it.
    try:
        status, provider_response = send_message(
            client=client,
            chat_id=target_chat_id,
            message_type=message_type,
            content=message,
            media_url=media_url,
        )
    except Exception as exc:
        error_text = f"OUTCOME UNKNOWN: {type(exc).__name__}: {exc}. Check Periskope and this message log before retrying."
        try:
            _finish_manual_send_log(message_log_id, "FAILED", error_text)
        except Exception:
            log.exception("Could not mark failed/unknown live send log %s", message_log_id)
        log.exception("Live send raised an exception for message log %s", message_log_id)
        raise HTTPException(status_code=502, detail="The send attempt raised an error and its outcome may be unknown. Check Periskope and message_logs before retrying to avoid a duplicate.") from exc

    provider_response = provider_response if isinstance(provider_response, dict) else {"response": str(provider_response)}
    provider_id = provider_response.get("message_id") or provider_response.get("id") or provider_response.get("unique_id") or provider_response.get("track_by")
    provider_id_str = str(provider_id) if provider_id is not None else None
    final_status = str(status or "QUEUED").strip().upper()
    if final_status not in {"QUEUED", "SENT", "DELIVERED", "READ", "FAILED"}:
        final_status = "QUEUED"

    if final_status == "FAILED":
        error_text = str(provider_response)[:3500] or "Periskope returned FAILED."
        try:
            _finish_manual_send_log(message_log_id, "FAILED", error_text, provider_id_str)
        except Exception:
            log.exception("Could not update failed live send log %s", message_log_id)
        raise HTTPException(status_code=502, detail="The existing Periskope adapter reported failure. Check Periskope and message_logs before deciding whether to retry.")

    audit_update_ok = True
    try:
        _finish_manual_send_log(message_log_id, final_status, None, provider_id_str)
    except Exception:
        audit_update_ok = False
        log.exception("Periskope accepted the request but message log %s could not be updated", message_log_id)

    if final_status in {"SENT", "DELIVERED", "READ"}:
        response_message = f"Periskope reported status {final_status}."
    else:
        response_message = "Periskope accepted/queued the request; delivery is not confirmed. Check Periskope for the final status."
    if not audit_update_ok:
        response_message += " The final database log update failed; do not resend until Periskope and message_logs are checked."

    log.info("Manual Periskope send completed with status=%s message_log_id=%s", final_status, message_log_id)
    return {
        "ok": True,
        "status": final_status,
        "message": response_message,
        "message_log_id": message_log_id,
        "periskope_message_id": provider_id_str,
        "recipient": recipient_name,
        "whatsapp_sending_enabled": True,
    }


@app.get("/api/no-send")
def no_send() -> dict[str, Any]:
    """Legacy status route; it now reports the guarded manual-send readiness state."""
    with db() as conn:
        status = inspect_schema(conn.cursor())
    return {
        "whatsapp_sending_enabled": bool(status["whatsapp_sending_enabled"]),
        "live_send_blockers": status.get("live_send_blockers", []),
        "message": "Manual sends are limited to one allowlisted member or group. Scheduler behaviour is unchanged; this endpoint does not run schedules or tier/phase bulk sends.",
    }


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
