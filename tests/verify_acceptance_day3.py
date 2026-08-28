"""Runs all 11 Day-3 acceptance criteria (see acceptance_criteria_day3.md)
against a real, live stack: real signup/login, real Qdrant, real BM25
refit, real Gemini generation. Uses FastAPI's TestClient (in-process, no
separate server needed) but every call is real -- no mocking.

Generates one throwaway PDF (via reportlab -- a test-only dependency, not
in requirements.txt, used nowhere in the app itself) containing a
fabricated, uniquely-identifiable fact, runs it through the real
authenticated /upload endpoint, and fully reverts the corpus (Qdrant
points, chunks.jsonl, bm25_vectorizer.json) back to its pre-run state
afterward in a finally block -- the same discipline used for the manual
validation this automates, so the script is safely re-runnable.

Frontend (criteria 8-10) and Docker Compose (criterion 11) are not
covered here -- they need a browser / a real `docker compose up` and are
verified manually per acceptance_criteria_day3.md's own sign-off section.

Usage: python -m tests.verify_acceptance_day3
"""

import shutil
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from src.api import app
from src.chunker import read_chunks_jsonl
from src.config import BM25_VECTORIZER_PATH, CHUNKS_PATH, SQLITE_LOG_PATH, UPLOADS_DIR
from src.indexer import (
    check_qdrant_reachable,
    delete_chunks_by_source_file,
    get_client,
    get_point_count,
    update_sparse_vectors,
)
from src.sparse_vectorizer import BM25SparseVectorizer

client = TestClient(app, raise_server_exceptions=False)
results: list[tuple[int, str, bool]] = []

# A fyYYYY year far from the real corpus (FY2022-23..FY2024-25) and from
# any manual smoke-test years used during development, so a stray leftover
# from a previous run can never collide with this run's own test data.
TEST_SOURCE_FILE = "verify_day3_fy2097.pdf"
UNIQUE_FACT_VALUE = "88888.88"
UNIQUE_KEYWORD = "snorklewhack"


def check(number: int, description: str, passed: bool, evidence: str) -> None:
    results.append((number, description, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] Criterion {number}: {description}")
    print(f"       {evidence}")
    print()


def make_test_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.setFont("Helvetica", 11)
    lines = [
        "Verify Day 3 Throwaway Report",
        "",
        "This document exists only to validate the real /upload ingestion",
        "pipeline via tests/verify_acceptance_day3.py -- it is deleted, and",
        "its effect on the index fully reverted, at the end of this run.",
        "",
        f"The {UNIQUE_KEYWORD.capitalize()} Division reported a Verification",
        f"Reserve of Rs {UNIQUE_FACT_VALUE} crore as at March 31, 2097. This",
        "figure is fabricated and unique to this automated verification run.",
    ]
    y = 740
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
    c.save()


def check_signup_and_login(username: str, password: str) -> str | None:
    r_signup = client.post("/signup", json={"username": username, "password": password})
    check(
        1,
        "A new user can sign up with a username/password",
        r_signup.status_code == 201,
        f"status={r_signup.status_code}, body={r_signup.json()}",
    )

    r_login = client.post("/login", json={"username": username, "password": password})
    token = r_login.json().get("access_token") if r_login.status_code == 200 else None
    check(
        2,
        "A signed-up user can log in and receive a valid token",
        r_login.status_code == 200 and bool(token),
        f"status={r_login.status_code}, has access_token={bool(token)}",
    )
    return token


def check_reject_missing_invalid_token() -> None:
    fake_pdf = ("x.pdf", b"%PDF-1.4 not a real pdf", "application/pdf")
    bad_headers = {"Authorization": "Bearer garbage.token.value"}

    qdrant = get_client()
    points_before = get_point_count(qdrant)

    no_token_ask = client.post("/ask", json={"query": "irrelevant"})
    bad_token_ask = client.post("/ask", json={"query": "irrelevant"}, headers=bad_headers)
    no_token_upload = client.post("/upload", files={"file": fake_pdf})
    bad_token_upload = client.post("/upload", files={"file": fake_pdf}, headers=bad_headers)

    points_after = get_point_count(qdrant)

    statuses = {
        "ask no-token": no_token_ask.status_code,
        "ask bad-token": bad_token_ask.status_code,
        "upload no-token": no_token_upload.status_code,
        "upload bad-token": bad_token_upload.status_code,
    }
    all_401 = all(s == 401 for s in statuses.values())
    # A 401 that still ran the upload behind the scenes would be a much
    # worse bug than a plain missing rejection -- confirmed here, not
    # assumed, same check done by hand while wiring /upload in api.py.
    index_untouched = points_before == points_after

    check(
        3,
        "POST /ask and POST /upload reject requests with no token or an invalid token (401)",
        all_401 and index_untouched,
        f"statuses={statuses}, index untouched (points {points_before} -> {points_after})={index_untouched}",
    )


def check_real_upload_ingestion(token: str, pdf_path: Path) -> dict | None:
    headers = {"Authorization": f"Bearer {token}"}

    r_ask_before = client.post(
        "/ask",
        json={"query": "What was Tata Steel's revenue from operations in FY2024-25?"},
        headers=headers,
    )

    with pdf_path.open("rb") as f:
        r_upload = client.post(
            "/upload",
            files={"file": (TEST_SOURCE_FILE, f.read(), "application/pdf")},
            headers=headers,
        )
    upload_ok = r_upload.status_code == 200
    upload_body = r_upload.json() if upload_ok else {}

    check(
        4,
        "A logged-in user's token successfully authorizes /ask and /upload calls",
        r_ask_before.status_code == 200 and upload_ok,
        f"ask status={r_ask_before.status_code}, upload status={r_upload.status_code}",
    )

    if not upload_ok:
        check(5, "Uploading a new PDF actually parses/chunks/embeds/indexes it", False, f"upload failed: {upload_body or r_upload.text}")
        check(6, "BM25 is re-fit across the full corpus after an upload", False, "skipped -- upload failed")
        return None

    r_ask_after = client.post(
        "/ask",
        json={"query": f"What was the Verification Reserve reported by the {UNIQUE_KEYWORD.capitalize()} Division?"},
        headers=headers,
    )
    ask_body = r_ask_after.json() if r_ask_after.status_code == 200 else {}
    answer = ask_body.get("answer", "")
    citations = ask_body.get("citations", [])
    cites_new_file_only = bool(citations) and all(c["source_file"] == TEST_SOURCE_FILE for c in citations)

    check(
        5,
        "Uploading a new PDF actually parses/chunks/embeds/indexes it (retrievable via a real /ask query)",
        r_ask_after.status_code == 200 and UNIQUE_FACT_VALUE in answer and cites_new_file_only,
        f"status={r_ask_after.status_code}, fact in answer={UNIQUE_FACT_VALUE in answer}, "
        f"citations={citations}",
    )

    vectorizer = BM25SparseVectorizer.load(BM25_VECTORIZER_PATH)
    keyword_in_vocab = UNIQUE_KEYWORD in vectorizer.vocab
    check(
        6,
        "BM25 is re-fit across the full corpus after an upload (vocab changed, new keyword sparse-retrievable)",
        keyword_in_vocab,
        f"unique keyword {UNIQUE_KEYWORD!r} present in refit bm25_vectorizer.json vocab={keyword_in_vocab}, "
        f"total_chunks after upload={upload_body.get('total_chunks')}",
    )

    return upload_body


def check_idempotent_reupload(token: str, pdf_path: Path, first_upload_body: dict) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    qdrant = get_client()
    points_before = get_point_count(qdrant)

    with pdf_path.open("rb") as f:
        r_reupload = client.post(
            "/upload",
            files={"file": (TEST_SOURCE_FILE, f.read(), "application/pdf")},
            headers=headers,
        )
    ok = r_reupload.status_code == 200
    body = r_reupload.json() if ok else {}
    points_after = get_point_count(qdrant)

    no_duplication = (
        ok
        and points_after == points_before
        and body.get("total_chunks") == first_upload_body.get("total_chunks")
        and body.get("chunks_replaced") == first_upload_body.get("chunks_added")
    )
    check(
        7,
        "Re-uploading the same PDF twice does not duplicate chunks/points",
        no_duplication,
        f"status={r_reupload.status_code}, points {points_before} -> {points_after}, "
        f"total_chunks {first_upload_body.get('total_chunks')} -> {body.get('total_chunks')}, "
        f"chunks_replaced={body.get('chunks_replaced')} (expected {first_upload_body.get('chunks_added')})",
    )


def sweep_stray_users() -> None:
    """A previous run killed externally (e.g. a shell/tool timeout) skips
    its own finally block entirely -- confirmed live: a 2-minute tool
    timeout during development left exactly one 'verify_day3_<hex>' user
    row behind. Swept here, before creating this run's own user, so
    re-runs self-heal instead of accumulating stray rows forever."""
    conn = sqlite3.connect(SQLITE_LOG_PATH)
    conn.execute("DELETE FROM users WHERE username LIKE 'verify_day3_%'")
    conn.commit()
    conn.close()


def cleanup(username: str, chunks_backup: Path, bm25_backup: Path) -> None:
    """Best-effort full revert, run in a finally block so a failed
    assertion above never leaves the real corpus/index/users table dirty
    for the next run."""
    qdrant = get_client()
    delete_chunks_by_source_file(qdrant, TEST_SOURCE_FILE)

    if chunks_backup.exists() and bm25_backup.exists():
        shutil.copy(chunks_backup, CHUNKS_PATH)
        shutil.copy(bm25_backup, BM25_VECTORIZER_PATH)
        chunks = read_chunks_jsonl(CHUNKS_PATH)
        vectorizer = BM25SparseVectorizer.load(BM25_VECTORIZER_PATH)
        sparse_vecs = [vectorizer.doc_vector(c.text) for c in chunks]
        update_sparse_vectors(qdrant, chunks, sparse_vecs)

    conn = sqlite3.connect(SQLITE_LOG_PATH)
    conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()

    stray = UPLOADS_DIR / TEST_SOURCE_FILE
    if stray.exists():
        stray.unlink()


def main() -> None:
    check_qdrant_reachable()
    sweep_stray_users()

    tmp_dir = Path(tempfile.mkdtemp(prefix="verify_day3_"))
    chunks_backup = tmp_dir / "chunks_backup.jsonl"
    bm25_backup = tmp_dir / "bm25_backup.json"
    shutil.copy(CHUNKS_PATH, chunks_backup)
    shutil.copy(BM25_VECTORIZER_PATH, bm25_backup)

    pdf_path = tmp_dir / TEST_SOURCE_FILE
    make_test_pdf(pdf_path)

    username = f"verify_day3_{uuid.uuid4().hex[:8]}"
    password = "verify_day3_password"

    try:
        print("=== Auth ===\n")
        token = check_signup_and_login(username, password)
        check_reject_missing_invalid_token()

        print("=== Real Upload Ingestion ===\n")
        if token is None:
            check(4, "A logged-in user's token successfully authorizes /ask and /upload calls", False, "no token from login -- skipped")
            check(5, "Uploading a new PDF actually parses/chunks/embeds/indexes it", False, "skipped -- no token")
            check(6, "BM25 is re-fit across the full corpus after an upload", False, "skipped -- no token")
            check(7, "Re-uploading the same PDF twice does not duplicate chunks/points", False, "skipped -- no token")
        else:
            first_upload_body = check_real_upload_ingestion(token, pdf_path)
            if first_upload_body is None:
                check(7, "Re-uploading the same PDF twice does not duplicate chunks/points", False, "skipped -- first upload failed")
            else:
                check_idempotent_reupload(token, pdf_path, first_upload_body)

        print("=== Sign-off (criteria 1-7; 8-11 are manual/browser/docker, see acceptance_criteria_day3.md) ===")
        passed_count = sum(1 for _, _, p in results if p)
        for number, description, passed in sorted(results, key=lambda r: r[0]):
            print(f"  [{'x' if passed else ' '}] {number}. {description}")
        print(f"\n{passed_count}/{len(results)} automated criteria passed.")
        if passed_count != len(results):
            sys.exit(1)
    finally:
        cleanup(username, chunks_backup, bm25_backup)
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
