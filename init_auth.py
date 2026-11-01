"""Explicit, one-time administrator provisioning; never touches business tables."""
from __future__ import annotations

import getpass
import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

from auth import password_hasher


def main() -> int:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)
    database_url = os.getenv("DATABASE_URL", "").strip()
    schema = os.getenv("DATABASE_SCHEMA", "public").strip() or "public"
    if not database_url or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        print("DATABASE_URL and a valid DATABASE_SCHEMA are required.")
        return 1
    username = input("Administrator username: ").strip()
    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not username or len(username) > 128 or len(password) < 15 or len(password) > 1024 or password != confirmation:
        print("Use a username of at most 128 characters and matching passwords of 15–1024 characters.")
        return 1
    password_hash = password_hasher.hash(password)
    try:
        with psycopg.connect(database_url, connect_timeout=4) as conn:
            table = sql.SQL("{}.auth_users").format(sql.Identifier(schema))
            conn.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """).format(table))
            conn.execute(sql.SQL("LOCK TABLE {} IN EXCLUSIVE MODE").format(table))
            if conn.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(table)).fetchone()[0]:
                print("Authentication users already exist; no account was changed.")
                return 1
            conn.execute(sql.SQL("INSERT INTO {} (username, password_hash, role) VALUES (%s, %s, %s)").format(table), (username, password_hash, "admin"))
    except psycopg.Error:
        print("Could not provision authentication. Check database access and table-creation permissions.")
        return 1
    print("Administrator created. No existing application tables were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
