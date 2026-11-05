"""Validate and encode locally stored uploads for the Periskope API."""
from __future__ import annotations

import base64
import os
from pathlib import Path

MIB = 1024 * 1024
EXTENSIONS = {
    ".png": ("image", "image/png"), ".jpg": ("image", "image/jpeg"), ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"), ".gif": ("image", "image/gif"),
    ".mp3": ("audio", "audio/mpeg"), ".wav": ("audio", "audio/wav"), ".m4a": ("audio", "audio/mp4"),
    ".aac": ("audio", "audio/aac"), ".ogg": ("audio", "audio/ogg"), ".opus": ("audio", "audio/ogg"),
    ".mp4": ("video", "video/mp4"), ".mov": ("video", "video/quicktime"), ".webm": ("video", "video/webm"), ".m4v": ("video", "video/x-m4v"),
    ".pdf": ("document", "application/pdf"), ".txt": ("document", "text/plain"), ".csv": ("document", "text/csv"),
    ".doc": ("document", "application/msword"), ".docx": ("document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xls": ("document", "application/vnd.ms-excel"), ".xlsx": ("document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".ppt": ("document", "application/vnd.ms-powerpoint"), ".pptx": ("document", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}


def local_media_payload(media_url: str, expected_type: str, upload_dir: Path | None = None) -> dict[str, str]:
    """Only accept a single file directly under the configured upload directory."""
    root = Path(upload_dir or os.getenv("UPLOAD_DIR", Path(__file__).resolve().parent / "data" / "uploads")).expanduser().resolve()
    if not media_url.startswith("/uploads/"):
        raise ValueError("Invalid local media reference.")
    name = media_url.removeprefix("/uploads/")
    if not name or Path(name).name != name or "\\" in name:
        raise ValueError("Invalid local media reference.")
    target = root / name
    if target.is_symlink() or target.resolve().parent != root:
        raise ValueError("Invalid local media reference.")
    filename = name.split("_", 1)[1] if len(name.split("_", 1)) == 2 and len(name.split("_", 1)[0]) == 32 else name
    media = EXTENSIONS.get(Path(filename).suffix.lower())
    if not media or media[0] != expected_type.lower():
        raise ValueError("Unsupported or mismatched media type.")
    kind, mime = media
    limit = (100 if kind == "document" else 16) * MIB
    try:
        with target.open("rb") as source:
            content = source.read(limit + 1)
    except OSError as exc:
        raise ValueError("Uploaded media is unavailable.") from exc
    if not content or len(content) > limit:
        raise ValueError(f"Media must be nonempty and at most {limit // MIB} MB for {kind}.")
    return {"type": kind, "filedata": base64.b64encode(content).decode("ascii"), "mimetype": mime, "filename": filename}
