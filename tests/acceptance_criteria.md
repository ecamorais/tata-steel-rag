# Acceptance Criteria — Day 1 (Ingestion + Hybrid Retrieval)

These must all pass before Day 1 is considered done. Claude Code should state
explicitly, for each item, how the implementation satisfies it — not just
assert that it does.

## Parsing & Chunking

1. **No table is ever split across two chunks.** A table found on a page
   stays entirely within a single chunk, even if this makes that chunk
   larger than the target chunk size for prose.
2. **Every chunk has a non-null `fiscal_year`** that correctly matches its
   source filename (tata-steel-fy2023.pdf → "FY2022-23",
   tata-steel-fy2024.pdf → "FY2023-24", tata-steel-fy2025.pdf → "FY2024-25").
3. **Every chunk has a non-null `source_file` and `page_number`.**
4. **A chunk tagged `chunk_type="table"` contains at most one table.**
5. **Total chunk count is sane for 3 annual reports of this size** — logged
   after chunking, and manually spot-checked against a rough page count
   estimate (not just accepted blindly).

## Indexing

6. **Re-running ingestion on unchanged PDFs does not create duplicate points**
   in the Qdrant collection. Verify by checking the collection's point count
   before and after a second run — it must be identical.
7. **Every point in Qdrant has its full metadata payload** (source_file,
   fiscal_year, page_number, section_title, chunk_type) — spot-check at
   least 3 points directly via the Qdrant client, not just trust the
   ingestion code.

## Retrieval Quality

8. **A query for "Tata Steel FY2024-25 net profit" retrieves at least one
   chunk from tata-steel-fy2025.pdf in the top 5 hybrid results.**
9. **A query for "Tata Steel FY2022-23 net profit" retrieves at least one
   chunk from tata-steel-fy2023.pdf in the top 5 hybrid results** — this
   confirms fiscal_year metadata and retrieval actually discriminate between
   years, not just returning whichever year has the most/best-formatted text.
10. **A vague, non-financial query (e.g. "Tata Steel workforce diversity
    initiatives") does not return only table chunks** — confirms prose
    chunking and dense retrieval are functioning, not just table extraction.
11. **A nonsense/out-of-scope query (e.g. "what is the capital of France")
    should not return high-confidence-looking results** — sanity check that
    scores meaningfully drop for irrelevant queries, useful later for
    deciding a "not found" threshold in generation.

## Sign-off

Each item above must be checked off with evidence (a log line, a printed
query result, a Qdrant point count) — not just marked done on the strength
of the code compiling and running without errors.