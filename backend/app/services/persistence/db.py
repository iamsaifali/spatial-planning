"""SQLite (stdlib) - designs and mock orders only; the catalog stays in memory."""

import secrets
import sqlite3
import string
from contextlib import contextmanager
from pathlib import Path

_ALPHABET = string.ascii_letters + string.digits

_db_path: Path | None = None


def new_id(length: int = 10) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def init_db(path: Path) -> None:
    global _db_path
    _db_path = path
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS designs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                total_price INTEGER NOT NULL DEFAULT 0,
                item_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                design_id TEXT,
                lines_json TEXT NOT NULL,
                contact_json TEXT NOT NULL,
                total INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                display_total INTEGER NOT NULL DEFAULT 0,
                eta_days INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );
            """
        )


@contextmanager
def get_conn():
    if _db_path is None:
        raise RuntimeError("init_db() was not called")
    conn = sqlite3.connect(_db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
