# Acceptance Criteria — Day 2 (Generation + API)

These must all pass before Day 2 is considered done. Claude Code should
state explicitly, for each item, how the implementation satisfies it —
not just assert that it does.

## Generation Quality

1. **A query with a clear, known answer produces the correct figure.**
   Use a fact already verified against the source PDF on Day 1 — e.g.
   "What was Tata Steel's Property, Plant and Equipment as at March 31,
   2025?" should return ₹93,203.83 crore (confirmed against the Balance
   Sheet on page 280 during Day 1 review), not a hallucinated or
   misattributed number.

   **Known limitation, currently failing:** this specific query does not
   retrieve the Balance Sheet chunk (page 280) — a single dense/sparse
   vector for an 83-row table dilutes relevance for any one line item
   below what natural-language phrasing can reach. Tried and confirmed not
   to fix it: 5 alternative phrasings (bare phrase, with "Balance Sheet",
   with surrounding line items) all fail to retrieve it even at top 10.
   Gemini correctly answers "not found in the provided documents" given
   the incomplete context rather than fabricating — the generation layer
   is behaving correctly given what retrieval hands it. See CLAUDE.md's
   "Known limitations" section for what was tried on the retrieval side.

2. **Every generated answer includes at least one citation** — source_file
   and page_number — for each factual claim it makes. An answer with a
   number but no citation is a failure, regardless of whether the number
   is correct.

3. **Citations are accurate, not just present.** Spot-check that a cited
   page_number actually contains the fact being cited (cross-reference
   against the retrieved chunk, not just trust the model's claim) — a
   plausible-looking but wrong citation is worse than no citation.

4. **A query with no support in the indexed corpus triggers an explicit
   refusal, not a fabrication.** E.g. "What was Tata Steel's profit in
   FY2019-20?" (outside the 3 indexed years) must produce something like
   "not found in the provided documents" — never a plausible-sounding
   invented figure.

5. **A query answerable only from a table chunk produces a correct
   answer**, confirming table serialization (the `|`-joined row format
   from chunker.py) survives all the way through prompt assembly and the
   model can actually parse it — not just that retrieval found the right
   chunk.

6. **A cross-year comparison query is handled correctly.** E.g. "How did
   Tata Steel's revenue from operations change between FY2023-24 and
   FY2024-25?" should cite figures from both years correctly, not
   conflate them or cite only one.

7. **The `fiscal_year` hard filter is actually usable end-to-end** — if
   the API/prompt layer supports scoping a question to one year (e.g. via
   a parameter or detected from the query), confirm it changes retrieval
   results, not just that the underlying `hybrid_search` filter works in
   isolation (already proven on Day 1).

## API

8. **POST /ask** accepts a JSON body with at least a `query` field and
   returns a JSON response containing the answer text and a structured
   list of citations (not citations embedded only as unparseable prose).

9. **POST /ask returns a clean 4xx error, never a 500**, for malformed
   input: empty query string, missing `query` field, non-JSON body.

10. **POST /upload accepts a PDF file and returns a clear, explicit "not
    yet implemented" response** (e.g. HTTP 501 or a structured "coming in
    a future version" message) — it must not silently accept the file and
    do nothing, and must not crash.

11. **Every /ask call is logged** — query, retrieved chunks (with scores
    and metadata), the final assembled prompt, and the answer — to a
    persistent local store (file or SQLite). Verify by making a real call
    and then reading the log entry back, not by inspecting the logging
    code alone.

12. **A concurrent or rapid-fire sequence of /ask calls doesn't corrupt
    the log** (e.g. interleaved writes producing malformed JSON) — a
    lightweight check, not a full load test.

## Sign-off

Each item checked off with evidence — a real API response, a real log
entry, an actual PDF page cross-referenced — not just "the code runs
without error."