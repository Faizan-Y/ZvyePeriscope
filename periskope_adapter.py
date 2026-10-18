"""Adapter for the existing Periskope.py class.

Confirm the actual signatures in the local project before live sending.
"""
from __future__ import annotations

import os
from typing import Any

ALLOWED_LOG_STATUSES = {"QUEUED", "SENT", "DELIVERED", "READ", "FAILED"}


def build_client():
    from Periskope import Periskope  # type: ignore[import-not-found]

    # Fail fast in live mode instead of discovering a missing credential one
    # failed send at a time. build_client is only called when not dry-run.
    missing = [
        name
        for name in ("PERISKOPE_API_KEY", "PERISKOPE_PHONE")
        if not (os.getenv(name) or "").strip()
    ]
    if missing:
        raise RuntimeError(
            "Live sending requires these environment variables: " + ", ".join(missing)
        )
    return Periskope()


def send_message(
    client: Any, chat_id: str, message_type: str, content: str, media_url: str | None
) -> tuple[str, dict[str, Any]]:
    kind = message_type.upper()
    if kind == "TEXT":
        raw = client.send_text(chat_id, content)
    elif kind in {"IMAGE", "VIDEO", "AUDIO", "DOCUMENT"}:
        if not media_url:
            raise ValueError(f"Template is {kind}, but templates.media_url is empty.")
        raw = client.send_media(chat_id, media_url, kind.lower(), caption=content or None)
    elif kind == "LOCATION":
        raise NotImplementedError("LOCATION sending is not implemented in this scheduler slice.")
    else:
        raise ValueError(f"Unsupported template message_type: {kind}")

    response = _normalize_response(raw)
    raw_status = str(response.get("status", "QUEUED")).strip().upper()
    if raw_status in {"ERROR", "FAILED", "FAILURE"} or response.get("success") is False:
        return "FAILED", response
    if raw_status in ALLOWED_LOG_STATUSES:
        return raw_status, response
    return "QUEUED", response


def _normalize_response(raw_response: Any) -> dict[str, Any]:
    if isinstance(raw_response, dict):
        response = dict(raw_response)
        for key in ("data", "result"):
            nested = response.get(key)
            if isinstance(nested, dict):
                for nested_key, value in nested.items():
                    response.setdefault(nested_key, value)
        return response
    if hasattr(raw_response, "status_code"):
        status_code = int(raw_response.status_code)
        try:
            body = raw_response.json()
        except Exception:
            body = {"body": str(getattr(raw_response, "text", ""))}
        if not isinstance(body, dict):
            body = {"body": body}
        body.setdefault("http_status", status_code)
        if status_code >= 400:
            raise RuntimeError(f"Periskope HTTP {status_code}: {body}")
        return body
    if raw_response is None:
        return {}
    return {"raw_response": str(raw_response)}
