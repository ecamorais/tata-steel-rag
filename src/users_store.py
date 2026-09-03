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


def _ensure_email_verification_columns(conn: sqlite3.Connection) -> None:
    """Additive migration: users predates email/verification columns, so
    CREATE TABLE IF NOT EXISTS alone won't add them to an already-existing
    table file. is_verified defaults to 1 so existing rows are treated as
    already verified -- no forced re-verification -- while create_user()
    always explicitly inserts 0 for a brand new signup, overriding this
    table-level default at insert time. Same guarded-ALTER-TABLE pattern
    as logging_store.py's username migration."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "email" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "verification_token" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN verification_token TEXT")
    if "is_verified" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 1")


def init_users_table(path: str | Path = SQLITE_LOG_PATH) -> None:
    conn = _connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        _ensure_email_verification_columns(conn)
        conn.commit()
    finally:
        conn.close()


def create_user(
    username: str,
    password_hash: str,
    email: str,
    verification_token: str,
    path: str | Path = SQLITE_LOG_PATH,
) -> int:
    conn = _connect(path)
    try:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, created_at, email, verification_token, is_verified) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (username, password_hash, datetime.now(timezone.utc).isoformat(), email, verification_token),
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


def get_user_by_verification_token(token: str, path: str | Path = SQLITE_LOG_PATH) -> dict | None:
    conn = _connect(path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE verification_token = ?", (token,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_user_verified(user_id: int, path: str | Path = SQLITE_LOG_PATH) -> None:
    # Clears verification_token too -- makes the token single-use, so the
    # same emailed link can't be replayed after the account is verified.
    conn = _connect(path)
    try:
        conn.execute(
            "UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()
