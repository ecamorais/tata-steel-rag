import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.config import SQLITE_LOG_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    query TEXT NOT NULL,
    fiscal_year_filter TEXT,
    retrieved_chunks_json TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    answer_json TEXT NOT NULL
)
"""


def _connect(path: str | Path = SQLITE_LOG_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # timeout: if the DB is momentarily locked by a concurrent writer, wait
    # up to 10s instead of raising immediately -- combined with WAL mode
    # (set once in init_db, persists in the DB file), this is what keeps
    # concurrent/rapid-fire writes from corrupting the log (criterion 12).
    conn = sqlite3.connect(path, timeout=10)
    return conn


def _ensure_username_column(conn: sqlite3.Connection) -> None:
    """Additive migration for per-user history: query_log predates the
    username column, so CREATE TABLE IF NOT EXISTS alone won't add it to an
    already-existing table file. Guarded on table_info rather than SQLite's
    own ADD COLUMN IF NOT EXISTS so this doesn't depend on a specific
    SQLite version underlying Python's bundled sqlite3. Existing rows get
    NULL -- accepted, not backfilled (pre-migration calls aren't
    attributable to a user)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(query_log)")}
    if "username" not in columns:
        conn.execute("ALTER TABLE query_log ADD COLUMN username TEXT")


def init_db(path: str | Path = SQLITE_LOG_PATH) -> None:
    conn = _connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        _ensure_username_column(conn)
        conn.commit()
    finally:
        conn.close()


def log_call(
    query: str,
    fiscal_year_filter: str | None,
    retrieved_chunks: list[dict],
    prompt_text: str,
    answer: dict,
    username: str,
    path: str | Path = SQLITE_LOG_PATH,
) -> int:
    conn = _connect(path)
    try:
        cursor = conn.execute(
            "INSERT INTO query_log "
            "(timestamp, query, fiscal_year_filter, retrieved_chunks_json, prompt_text, answer_json, username) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                query,
                fiscal_year_filter,
                json.dumps(retrieved_chunks, ensure_ascii=False),
                prompt_text,
                json.dumps(answer, ensure_ascii=False),
                username,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_call(call_id: int, path: str | Path = SQLITE_LOG_PATH) -> dict | None:
    conn = _connect(path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM query_log WHERE id = ?", (call_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["retrieved_chunks"] = json.loads(result.pop("retrieved_chunks_json"))
        result["answer"] = json.loads(result.pop("answer_json"))
        return result
    finally:
        conn.close()


def get_all_calls(path: str | Path = SQLITE_LOG_PATH) -> list[dict]:
    conn = _connect(path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM query_log ORDER BY id").fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["retrieved_chunks"] = json.loads(result.pop("retrieved_chunks_json"))
            result["answer"] = json.loads(result.pop("answer_json"))
            results.append(result)
        return results
    finally:
        conn.close()


def get_calls_by_username(username: str, limit: int = 50, path: str | Path = SQLITE_LOG_PATH) -> list[dict]:
    """Most-recent-first, scoped to one user. A NULL username (rows logged
    before this column existed) never matches this equality filter, so
    pre-migration calls simply don't appear in anyone's history -- the
    accepted no-backfill behavior, not a bug."""
    conn = _connect(path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM query_log WHERE username = ? ORDER BY id DESC LIMIT ?",
            (username, limit),
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["retrieved_chunks"] = json.loads(result.pop("retrieved_chunks_json"))
            result["answer"] = json.loads(result.pop("answer_json"))
            results.append(result)
        return results
    finally:
        conn.close()
