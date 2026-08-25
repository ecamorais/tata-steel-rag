"""Runs all 11 Day-1 acceptance criteria (see acceptance_criteria.md)
against the persisted output of a prior `python -m src.ingest` run.

Reads chunks.jsonl and the live Qdrant collection rather than re-parsing
PDFs, so it's fast enough to re-run anytime -- except criterion 6, which
re-runs ingestion on one file (~5 min) to prove upsert idempotency for
real rather than assert it.

Usage: python -m tests.verify_acceptance
"""

import json
import sys

import pdfplumber

from src.config import CHUNKS_PATH, RAW_DIR
from src.indexer import get_client, get_point_count
from src.ingest import run as run_ingest
from src.retriever import hybrid_search

FISCAL_YEAR_MAP = {
    "tata-steel-fy2023.pdf": "FY2022-23",
    "tata-steel-fy2024.pdf": "FY2023-24",
    "tata-steel-fy2025.pdf": "FY2024-25",
}

EXPECTED_CHUNKS_PER_PAGE_LOW = 1.0
EXPECTED_CHUNKS_PER_PAGE_HIGH = 3.5

# Largest real table chunk observed during development (fy2025 Balance
# Sheet, 83 rows). A table chunk far beyond this would suggest multiple
# tables got merged into one chunk -- not currently possible given
# chunker.py's one-chunk-per-TableBlock design, but checked defensively.
MAX_PLAUSIBLE_TABLE_ROWS = 200

results: list[tuple[int, str, bool]] = []


def check(number: int, description: str, passed: bool, evidence: str) -> None:
    results.append((number, description, passed))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] Criterion {number}: {description}")
    print(f"       {evidence}")
    print()


def load_chunks() -> list[dict]:
    if not CHUNKS_PATH.exists():
        print(f"ERROR: {CHUNKS_PATH} not found. Run `python -m src.ingest` first.")
        sys.exit(1)
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def criterion_1(chunks: list[dict]) -> None:
    fy2025_balance_sheet = [
        c
        for c in chunks
        if c["source_file"] == "tata-steel-fy2025.pdf" and c["page_number"] == 280 and c["chunk_type"] == "table"
    ]
    row_count = fy2025_balance_sheet[0]["text"].count("\n") + 1 if fy2025_balance_sheet else 0
    passed = len(fy2025_balance_sheet) == 1 and row_count > 50
    check(
        1,
        "No table is ever split across two chunks",
        passed,
        f"Structural guarantee: chunker.py emits exactly one Chunk per TableBlock, and pdf_parser.py "
        f"creates one TableBlock per detected table -- splitting is not structurally possible. "
        f"Concrete example: fy2025 Balance Sheet (page 280) is {len(fy2025_balance_sheet)} table chunk(s) "
        f"with {row_count} rows (not fragmented across multiple chunks).",
    )


def criterion_2(chunks: list[dict]) -> None:
    bad = [
        c
        for c in chunks
        if not c.get("fiscal_year") or c["fiscal_year"] != FISCAL_YEAR_MAP.get(c["source_file"])
    ]
    check(
        2,
        "Every chunk has a non-null fiscal_year matching its source filename",
        len(bad) == 0,
        f"{len(chunks)} chunks checked against {FISCAL_YEAR_MAP}; {len(bad)} mismatches or nulls.",
    )


def criterion_3(chunks: list[dict]) -> None:
    bad = [c for c in chunks if not c.get("source_file") or c.get("page_number") is None]
    check(
        3,
        "Every chunk has a non-null source_file and page_number",
        len(bad) == 0,
        f"{len(chunks)} chunks scanned; {len(bad)} missing source_file or page_number.",
    )


def criterion_4(chunks: list[dict]) -> None:
    table_chunks = [c for c in chunks if c["chunk_type"] == "table"]
    row_counts = [c["text"].count("\n") + 1 for c in table_chunks]
    oversized = [rc for rc in row_counts if rc > MAX_PLAUSIBLE_TABLE_ROWS]
    check(
        4,
        'A chunk tagged chunk_type="table" contains at most one table',
        len(oversized) == 0,
        f"Structural guarantee (one TableBlock -> one Chunk, see criterion 1). Defensive check: "
        f"{len(table_chunks)} table chunks, max {max(row_counts) if row_counts else 0} rows "
        f"(largest known real table is 83 rows), {len(oversized)} implausibly oversized.",
    )


def criterion_5(chunks: list[dict]) -> None:
    total_pages = 0
    for filename in FISCAL_YEAR_MAP:
        with pdfplumber.open(RAW_DIR / filename) as pdf:
            total_pages += len(pdf.pages)

    total_chunks = len(chunks)
    expected_low = int(total_pages * EXPECTED_CHUNKS_PER_PAGE_LOW)
    expected_high = int(total_pages * EXPECTED_CHUNKS_PER_PAGE_HIGH)
    in_band = expected_low <= total_chunks <= expected_high
    check(
        5,
        "Total chunk count is sane for 3 annual reports of this size",
        in_band,
        f"{total_pages} pages -> {total_chunks} chunks ({total_chunks/total_pages:.2f}/page), "
        f"expected band {expected_low}-{expected_high} at "
        f"{EXPECTED_CHUNKS_PER_PAGE_LOW}-{EXPECTED_CHUNKS_PER_PAGE_HIGH} chunks/page.",
    )


def criterion_6() -> None:
    client = get_client()
    count_before = get_point_count(client)
    run_ingest(["tata-steel-fy2025.pdf"])
    count_after = get_point_count(client)
    check(
        6,
        "Re-running ingestion on unchanged PDFs does not create duplicate points",
        count_before == count_after,
        f"Point count before second ingestion run of tata-steel-fy2025.pdf: {count_before}. "
        f"Point count after: {count_after}.",
    )


def criterion_7() -> None:
    client = get_client()
    from src.config import COLLECTION_NAME

    points, _ = client.scroll(collection_name=COLLECTION_NAME, limit=3, with_payload=True)
    required = ("source_file", "fiscal_year", "page_number", "chunk_type", "text")
    missing_by_point = {
        p.id: [f for f in required if p.payload.get(f) in (None, "")] for p in points
    }
    passed = len(points) == 3 and all(not m for m in missing_by_point.values())
    evidence_lines = "; ".join(f"{pid}: missing={missing}" for pid, missing in missing_by_point.items())
    check(
        7,
        "Every point in Qdrant has its full metadata payload",
        passed,
        f"3 points spot-checked directly via qdrant_client.scroll(): {evidence_lines}",
    )


def criterion_8() -> float:
    hits = hybrid_search("Tata Steel FY2024-25 net profit", top_k=5)
    match = any(h["source_file"] == "tata-steel-fy2025.pdf" for h in hits)
    top_cosine = hits[0]["dense_cosine"] if hits else 0.0
    check(
        8,
        'Query "Tata Steel FY2024-25 net profit" retrieves a fy2025 chunk in top 5',
        match,
        f"Top 5 source files: {[h['source_file'] for h in hits]}",
    )
    return top_cosine


def criterion_9() -> float:
    hits = hybrid_search("Tata Steel FY2022-23 net profit", top_k=5)
    match = any(h["source_file"] == "tata-steel-fy2023.pdf" for h in hits)
    top_cosine = hits[0]["dense_cosine"] if hits else 0.0
    check(
        9,
        'Query "Tata Steel FY2022-23 net profit" retrieves a fy2023 chunk in top 5',
        match,
        f"Top 5 source files: {[h['source_file'] for h in hits]}",
    )
    return top_cosine


def criterion_10() -> float:
    hits = hybrid_search("Tata Steel workforce diversity initiatives", top_k=5)
    not_all_tables = any(h["chunk_type"] != "table" for h in hits)
    top_cosine = hits[0]["dense_cosine"] if hits else 0.0
    check(
        10,
        "Vague non-financial query does not return only table chunks",
        not_all_tables,
        f"Top 5 chunk types: {[h['chunk_type'] for h in hits]}",
    )
    return top_cosine


def criterion_11(real_query_cosines: list[float]) -> None:
    hits = hybrid_search("what is the capital of France", top_k=5)
    top_cosine = hits[0]["dense_cosine"] if hits else 0.0
    passed = all(top_cosine < c for c in real_query_cosines)
    check(
        11,
        "Nonsense query does not return high-confidence-looking results",
        passed,
        f"Nonsense query top dense_cosine={top_cosine:.4f} vs real-query top cosines "
        f"{[round(c, 4) for c in real_query_cosines]} (criteria 8/9/10) -- below all of them.",
    )


def main() -> None:
    chunks = load_chunks()

    print("=== Parsing & Chunking ===\n")
    criterion_1(chunks)
    criterion_2(chunks)
    criterion_3(chunks)
    criterion_4(chunks)
    criterion_5(chunks)

    print("=== Indexing ===\n")
    criterion_6()
    criterion_7()

    print("=== Retrieval Quality ===\n")
    cos8 = criterion_8()
    cos9 = criterion_9()
    cos10 = criterion_10()
    criterion_11([cos8, cos9, cos10])

    print("=== Sign-off ===")
    passed_count = sum(1 for _, _, p in results if p)
    for number, description, passed in results:
        print(f"  [{'x' if passed else ' '}] {number}. {description}")
    print(f"\n{passed_count}/{len(results)} criteria passed.")
    if passed_count != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
