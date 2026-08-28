import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.config import SQLITE_LOG_PATH

# Same SQLite file as query_log -- one small table, not worth managing a
# second DB file for.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def _connect(path: str | Path = SQLITE_LOG_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    return conn


def init_users_table(path: str | Path = SQLITE_LOG_PATH) -> None:
    conn = _connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def create_user(username: str, password_hash: str, path: str | Path = SQLITE_LOG_PATH) -> int:
    conn = _connect(path)
    try:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"username {username!r} is already taken") from e
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_user_by_username(username: str, path: str | Path = SQLITE_LOG_PATH) -> dict | None:
    conn = _connect(path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
