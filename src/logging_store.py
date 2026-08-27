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


def init_db(path: str | Path = SQLITE_LOG_PATH) -> None:
    conn = _connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def log_call(
    query: str,
    fiscal_year_filter: str | None,
    retrieved_chunks: list[dict],
    prompt_text: str,
    answer: dict,
    path: str | Path = SQLITE_LOG_PATH,
) -> int:
    conn = _connect(path)
    try:
        cursor = conn.execute(
            "INSERT INTO query_log "
            "(timestamp, query, fiscal_year_filter, retrieved_chunks_json, prompt_text, answer_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                query,
                fiscal_year_filter,
                json.dumps(retrieved_chunks, ensure_ascii=False),
                prompt_text,
                json.dumps(answer, ensure_ascii=False),
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
