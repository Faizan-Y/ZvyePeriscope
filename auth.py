"""Portal authentication, independent of the scheduler and business tables."""
from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from psycopg import sql
from psycopg.rows import dict_row
from starlette.responses import JSONResponse, RedirectResponse, Response

COOKIE_NAME = "zyvefit_session"
SESSION_SECONDS = 8 * 60 * 60
MAX_LOGIN_ATTEMPTS = 8
LOGIN_WINDOW_SECONDS = 15 * 60
password_hasher = PasswordHasher()


@dataclass(frozen=True)
class Session:
    user_id: int
    role: str
    expires_at: float


class SessionStore:
    """In-memory, revocable sessions; run the portal with one worker only."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, user_id: int, role: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._sessions = {key: session for key, session in self._sessions.items() if session.expires_at > now}
            self._sessions[token] = Session(user_id, role, now + SESSION_SECONDS)
        return token

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if session and session.expires_at <= time.monotonic():
                del self._sessions[token]
                return None
            return session

    def revoke(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(token, None)


class LoginLimiter:
    """Process-wide throttle; production also needs proxy-level rate limiting."""

    def __init__(self) -> None:
        self._attempts: list[float] = []
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            self._attempts = [attempt for attempt in self._attempts if now - attempt < LOGIN_WINDOW_SECONDS]
            if len(self._attempts) >= MAX_LOGIN_ATTEMPTS:
                return False
            self._attempts.append(now)
            return True


sessions = SessionStore()
login_limiter = LoginLimiter()
# A dummy hash makes unknown usernames go through the same password-hashing work.
_dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


def cookie_is_secure() -> bool:
    # Fail safe unless local HTTP is explicitly configured.
    return os.getenv("ZYVEFIT_COOKIE_SECURE", "true").strip().lower() != "false"


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def authenticate(database_url: str, schema: str, username: str, password: str) -> dict | None:
    if not database_url:
        raise RuntimeError("Database is not configured")
    with psycopg.connect(database_url, connect_timeout=4, row_factory=dict_row) as conn:
        row = conn.execute(
            sql.SQL("SELECT id, password_hash, role, is_active FROM {}.auth_users WHERE username = %s").format(sql.Identifier(schema)),
            (username,),
        ).fetchone()
    valid = verify_password(row["password_hash"] if row else _dummy_hash, password)
    if row and valid and row["is_active"] and row["role"] == "admin":
        return {"id": row["id"], "role": row["role"]}
    return None


def same_origin(request) -> bool:
    """Reject cross-origin unsafe requests, including login and logout CSRF."""
    origin = request.headers.get("origin")
    if origin:
        return secrets.compare_digest(origin.rstrip("/"), str(request.base_url).rstrip("/"))
    referer = request.headers.get("referer")
    if not referer:
        return False
    parsed = urlsplit(referer)
    return secrets.compare_digest(f"{parsed.scheme}://{parsed.netloc}", str(request.base_url).rstrip("/"))


PUBLIC_GET_PATHS = {"/login", "/login.html", "/login.css", "/assets/zyvefit-logo.png"}


async def auth_gate(request, call_next):
    path = request.url.path
    method = request.method.upper()
    public = (method in {"GET", "HEAD"} and path in PUBLIC_GET_PATHS) or (method == "POST" and path == "/login")
    if not public and not sessions.get(request.cookies.get(COOKIE_NAME)):
        if path.startswith("/api/") or path == "/openapi.json" or method not in {"GET", "HEAD"}:
            return JSONResponse({"detail": "Authentication required."}, status_code=401, headers={"Cache-Control": "no-store"})
        return RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})
    if method not in {"GET", "HEAD", "OPTIONS"} and not same_origin(request):
        return JSONResponse({"detail": "Cross-origin request rejected."}, status_code=403)
    response = await call_next(request)
    if path in {"/", "/index.html", "/login", "/login.html"} or path.startswith("/api/") or path.startswith("/uploads/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True, secure=cookie_is_secure(), samesite="strict", path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, httponly=True, secure=cookie_is_secure(), samesite="strict", path="/")
