"""Runs all 12 Day-2 acceptance criteria (see acceptance_criteria_day2.md)
against a real, live stack: real hybrid_search, real Gemini generation, real
SQLite log. Uses FastAPI's TestClient (in-process, no separate server needed)
but every call is real -- no mocking.

Usage: python -m tests.verify_acceptance_day2
"""

import concurrent.futures
import sqlite3
import sys
import time
import uuid

# Real answers routinely contain non-ASCII characters (Rs symbol, etc.).
# Windows' default console codepage (cp1252) can't encode them -- confirmed
# live: this crashed mid-run on a real Rs figure in a cross-year answer,
# aborting the script before later criteria even ran. Reconfigured to
# UTF-8 so evidence prints regardless of the host console's codepage.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient

from src.api import app
from src.config import SQLITE_LOG_PATH
from src.logging_store import get_all_calls, init_db

# raise_server_exceptions=False: an unhandled exception (e.g. a transient
# Gemini 503) should surface as a real HTTP 500 response, same as a real
# deployed server would return to a client -- not re-raised as a Python
# exception that crashes this script before the retry logic in ask() below
# ever gets a chance to run.
client = TestClient(app, raise_server_exceptions=False)

results: list[tuple[int, str, bool]] = []

# This script predates Day 3's auth work -- /ask and /upload became
# auth-gated after these criteria were originally written. A fresh
# throwaway user is created per run (same pattern as
# verify_acceptance_day3.py) and used for every call below; deleted in
# main()'s finally block.
_TEST_USERNAME = f"verify_day2_{uuid.uuid4().hex[:8]}"
_TEST_PASSWORD = "verify_day2_password"
_auth_headers: dict[str, str] = {}


def _authenticate() -> None:
    signup_response = client.post("/signup", json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD})
    if signup_response.status_code != 201:
        raise RuntimeError(f"could not sign up test user: {signup_response.status_code} {signup_response.text}")
    login_response = client.post("/login", json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD})
    if login_response.status_code != 200:
        raise RuntimeError(f"could not log in test user: {login_response.status_code} {login_response.text}")
    _auth_headers["Authorization"] = f"Bearer {login_response.json()['access_token']}"


def _cleanup_test_user() -> None:
    conn = sqlite3.connect(SQLITE_LOG_PATH)
    conn.execute("DELETE FROM users WHERE username = ?", (_TEST_USERNAME,))
    conn.commit()
    conn.close()


def check(number: int, description: str, passed: bool, evidence: str) -> None:
    results.append((number, description, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] Criterion {number}: {description}")
    print(f"       {evidence}")
    print()


def check_superseded(number: int, description: str, note: str) -> None:
    # `passed=None` marks a criterion as superseded rather than pass/fail --
    # excluded from the pass/fail tally in main()'s sign-off (a criterion
    # whose original assertion is intentionally no longer true isn't a
    # failure, and counting it as one misrepresents the actual state).
    results.append((number, description, None))
    print(f"[SUPERSEDED] Criterion {number}: {description}")
    print(f"       {note}")
    print()


def ask(query: str, fiscal_year: str | None = None, retries: int = 2):
    """Real /ask calls occasionally hit a transient Gemini 503 (observed
    during development: 'model is currently experiencing high demand', a
    free-tier capacity issue, not a bug). Retried here in the verification
    script only -- api.py itself has no retry logic, per plan."""
    body = {"query": query}
    if fiscal_year is not None:
        body["fiscal_year"] = fiscal_year
    response = None
    for attempt in range(retries + 1):
        response = client.post("/ask", json=body, headers=_auth_headers)
        if response.status_code == 200:
            return response
        if attempt < retries:
            time.sleep(5)
    return response


def _find_chunk(log_entry: dict, citation: dict) -> dict | None:
    return next(
        (
            c
            for c in log_entry["retrieved_chunks"]
            if c["source_file"] == citation["source_file"] and c["page_number"] == citation["page_number"]
        ),
        None,
    )


def check_ppe_query() -> None:
    """One real /ask call feeds criteria 1, 2, 3, 5, 8, 11 -- all about
    the same known-answer PP&E fact from different angles."""
    query = "What was Tata Steel's Property, Plant and Equipment as at March 31, 2025?"
    response = ask(query)
    ok = response.status_code == 200
    body = response.json() if ok else {}
    answer = body.get("answer", "")
    citations = body.get("citations", [])

    check(
        1,
        "A query with a clear, known answer produces the correct figure",
        ok and "93,203.83" in answer,
        f"status={response.status_code}, answer={answer!r}",
    )

    check(
        2,
        "Every generated answer includes at least one citation",
        ok and len(citations) >= 1,
        f"citations={citations}",
    )

    check(
        8,
        "POST /ask returns a structured citations list, not unparseable prose",
        ok and isinstance(body.get("citations"), list) and all(isinstance(c, dict) for c in citations),
        f"citations type={type(body.get('citations')).__name__}, sample={citations[:1]}",
    )

    log_entries = get_all_calls()
    last = log_entries[-1] if log_entries else None

    accurate_citation = None
    if last:
        for citation in citations:
            chunk = _find_chunk(last, citation)
            if chunk and "93,203.83" in chunk["text"]:
                accurate_citation = (citation, chunk["chunk_type"])
                break
    check(
        3,
        "Citations are accurate, not just present (cross-referenced against the actual retrieved chunk text)",
        accurate_citation is not None,
        f"citation {accurate_citation[0]!r} points to a retrieved chunk that actually contains '93,203.83'"
        if accurate_citation
        else f"none of {citations} pointed to a retrieved chunk containing the fact",
    )

    check(
        5,
        "A query answerable only from a table chunk produces a correct answer (table serialization survives to generation)",
        accurate_citation is not None and accurate_citation[1] == "table",
        f"the accurate citation above is chunk_type={accurate_citation[1]!r}" if accurate_citation else "no accurate citation found",
    )

    logged_correctly = last is not None and last["query"] == query and last["answer"]["answer"] == answer
    check(
        11,
        "Every /ask call is logged (query, retrieved chunks, prompt, answer all readable back)",
        logged_correctly,
        f"log row query matches={last['query'] == query if last else False}, "
        f"answer matches={last['answer']['answer'] == answer if last else False}, "
        f"retrieved_chunks count={len(last['retrieved_chunks']) if last else 0}, "
        f"prompt_text length={len(last['prompt_text']) if last else 0}",
    )


def check_unsupported_query() -> None:
    query = "What was Tata Steel's profit in FY2019-20?"
    response = ask(query)
    ok = response.status_code == 200
    body = response.json() if ok else {}
    refused = ok and body.get("found") is False and "not found" in body.get("answer", "").lower()
    check(
        4,
        "A query with no support in the indexed corpus triggers an explicit refusal, not a fabrication",
        refused,
        f"status={response.status_code}, found={body.get('found')}, answer={body.get('answer')!r}",
    )


def check_cross_year_query() -> None:
    query = "How did Tata Steel's revenue from operations change between FY2023-24 and FY2024-25?"
    response = ask(query)
    ok = response.status_code == 200
    body = response.json() if ok else {}
    answer = body.get("answer", "")
    citations = body.get("citations", [])

    # Checking the answer TEXT for both years, not just cited-chunk
    # fiscal_year metadata: a single filing's P&L legitimately reports the
    # prior year's comparative figures in the same chunk, so a citation to
    # one fy2025 chunk can correctly be the source for BOTH years' numbers
    # -- chunk-level fiscal_year alone would undercount that as "only one
    # year cited" even when the answer is fully correct.
    both_years_in_answer = "FY2023-24" in answer and "FY2024-25" in answer

    log_entries = get_all_calls()
    last = log_entries[-1] if log_entries else None
    years_cited = set()
    if last:
        for citation in citations:
            chunk = _find_chunk(last, citation)
            if chunk:
                years_cited.add(chunk["fiscal_year"])

    check(
        6,
        "A cross-year comparison query cites figures from both years, not just one",
        ok and both_years_in_answer and len(citations) >= 1,
        f"both years present in answer text={both_years_in_answer}, "
        f"cited chunk fiscal years={years_cited or 'none'}, answer={answer!r}",
    )


def check_fiscal_year_filter() -> None:
    query = "What was the revenue from operations?"
    filtered_response = ask(query, fiscal_year="FY2022-23")
    ok = filtered_response.status_code == 200
    body = filtered_response.json() if ok else {}
    citations = body.get("citations", [])

    log_entries = get_all_calls()
    last = log_entries[-1] if log_entries else None
    years_cited = set()
    if last:
        for citation in citations:
            chunk = _find_chunk(last, citation)
            if chunk:
                years_cited.add(chunk["fiscal_year"])

    only_target_year = ok and bool(citations) and years_cited == {"FY2022-23"}
    check(
        7,
        "The fiscal_year hard filter is usable end-to-end through the API, not just hybrid_search in isolation",
        only_target_year,
        f"query run with fiscal_year='FY2022-23' -> citation years: {years_cited or 'none'} (expected exactly {{'FY2022-23'}})",
    )


def check_malformed_input() -> None:
    # A valid token is attached here too -- these check body validation
    # (empty/missing query, non-JSON), not auth, so a real token isolates
    # that from the 401s that would otherwise mask the actual result.
    empty_query = client.post("/ask", json={"query": ""}, headers=_auth_headers)
    missing_field = client.post("/ask", json={"fiscal_year": "FY2024-25"}, headers=_auth_headers)
    non_json = client.post(
        "/ask",
        content=b"not json at all",
        headers={**_auth_headers, "Content-Type": "application/json"},
    )
    statuses = [empty_query.status_code, missing_field.status_code, non_json.status_code]
    all_4xx = all(400 <= s < 500 for s in statuses)
    check(
        9,
        "POST /ask returns a clean 4xx error, never a 500, for malformed input",
        all_4xx,
        f"empty query -> {statuses[0]}, missing field -> {statuses[1]}, non-JSON body -> {statuses[2]}",
    )


def check_upload_stub() -> None:
    check_superseded(
        10,
        "POST /upload accepts a PDF and returns a clear, explicit not-yet-implemented response",
        "SUPERSEDED by Day 3: /upload no longer returns a 501 stub -- Day 3 replaced it with "
        "real ingestion (parse/chunk/embed/index), verified by tests/verify_acceptance_day3.py "
        'criterion 5. This criterion\'s original assertion (expects a 501 "not implemented" '
        "response) is intentionally no longer true and is not re-tested here.",
    )


def check_concurrent_calls() -> None:
    # This checks corruption specifically -- whatever succeeds must produce
    # a clean, uncorrupted log row. It does NOT require all 4 calls to
    # succeed: under concurrent load a free-tier API can legitimately rate
    # limit some of them (observed: cumulative quota from earlier real
    # calls in this same run caused 2/4 to fail here even though an
    # isolated run of just these 4 succeeds 4/4) -- that's the generation
    # API's rate limiting, a separate concern from whether the log itself
    # gets corrupted.
    before_count = len(get_all_calls())

    def fire(i: int):
        return client.post("/ask", json={"query": f"What is Tata Steel? (concurrency probe {i})"}, headers=_auth_headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(fire, range(4)))

    expected_new_rows = sum(1 for r in responses if r.status_code == 200)
    after_entries = get_all_calls()
    added = len(after_entries) - before_count
    new_entries = after_entries[-added:] if added > 0 else []
    no_corruption = added == expected_new_rows and all(
        isinstance(e["answer"], dict) and isinstance(e["retrieved_chunks"], list) for e in new_entries
    )

    check(
        12,
        "A concurrent/rapid-fire sequence of /ask calls doesn't corrupt the log",
        no_corruption,
        f"4 concurrent calls -> statuses={[r.status_code for r in responses]}, "
        f"{expected_new_rows} succeeded -> {added} new log rows (should match), all valid JSON={no_corruption}",
    )


def main() -> None:
    # Fails fast with an actionable message if Qdrant/Docker has dropped --
    # called explicitly here (not just relying on api.py's lifespan hook)
    # because TestClient only runs lifespan startup when used as a context
    # manager, and this script uses a plain instance.
    from src.indexer import check_qdrant_reachable

    check_qdrant_reachable()

    init_db()

    try:
        _authenticate()

        print("=== Generation Quality ===\n")
        check_ppe_query()
        check_unsupported_query()
        check_cross_year_query()
        check_fiscal_year_filter()

        print("=== API ===\n")
        check_malformed_input()
        check_upload_stub()
        check_concurrent_calls()

        print("=== Sign-off ===")
        passed_count = sum(1 for _, _, p in results if p is True)
        superseded_count = sum(1 for _, _, p in results if p is None)
        active_count = len(results) - superseded_count
        for number, description, passed in sorted(results, key=lambda r: r[0]):
            marker = "~" if passed is None else ("x" if passed else " ")
            print(f"  [{marker}] {number}. {description}")
        print(f"\n{passed_count}/{active_count} active criteria passed ({superseded_count} superseded, not counted).")
        if passed_count != active_count:
            sys.exit(1)
    finally:
        _cleanup_test_user()


if __name__ == "__main__":
    main()
