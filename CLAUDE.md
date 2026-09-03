# CLAUDE.md

## Project overview

RAG (Retrieval-Augmented Generation) system built over Tata Steel's last
three annual reports (FY2023, FY2024, FY2025). This is a hands-on demo
project built for an interview — prioritize a working, explainable pipeline
over production hardening.

## Stack decisions

- **PDF parsing**: `pdfplumber`
- **Chunking**: structural chunking — chunks follow document structure
  (sections/headings), not fixed-size windows
- **Vector store**: Qdrant, run via Docker, accessed at `localhost:6333`
- **Retrieval**: native Qdrant hybrid search — dense + sparse vectors in the
  same collection, fused with **RRF (Reciprocal Rank Fusion)**
- **Embeddings**: `sentence-transformers`, model `bge-small-en-v1.5`

## Project structure

- `data/raw/` — source PDFs (the 3 annual reports)
- `data/processed/` — parsed/chunked output
- `src/` — application code (parsing, chunking, indexing, retrieval)
- `tests/` — tests

## Conventions

- **Chunk metadata schema** — every chunk carries:
  - `source_file`
  - `fiscal_year`
  - `page_number`
  - `section_title`
  - `chunk_type`
- **Never split a table across chunks.** A table is kept whole in a single
  chunk even if that makes the chunk larger than the target size.

## Workflow constraint

- Always propose a plan and wait for explicit approval before writing any
  code.
- Implement **one file at a time**. After each file, pause for a diff
  review before moving to the next file.

## Day 2 additions

- **Generation LLM**: Google Gemini API (free tier, no billing required),
  via the `google-genai` Python SDK (the older `google-generativeai`
  package is deprecated). Model: `gemini-3.6-flash`, pinned explicitly —
  `gemini-3.7-flash` was tried first and confirmed working, but started
  returning sustained 503 "high demand" errors; `gemini-3.6-flash` (the
  model Google's own API error recommends as the successor to the
  now-dead `gemini-2.5-flash`) has been stable. Structured output via
  `response_schema` on `client.models.generate_content()`.
- **Upload endpoint**: stub only for Day 2 — validates/saves the file and
  returns a "not yet implemented" style response. Full ingestion wiring
  (parse/chunk/embed/index, including BM25 refit across the whole corpus)
  is Day 3 scope, not Day 2.
- **API framework**: FastAPI
- **Prompt assembly**: inject retrieved chunks with inline citations
  (source_file, page_number, fiscal_year), explicit instruction to answer
  only from provided context and say "not found in the provided documents"
  when the context doesn't support an answer
- **Logging**: every /ask call logs query -> retrieved chunks -> final
  prompt -> answer, to a local file/SQLite (exact format TBD in Day 2 plan)

## Known limitations

- **Large-table retrieval gap (largely resolved; one specific table
  remains a known exception).** A table chunk gets a single dense +
  sparse vector for its entire content; for a large table (e.g. the
  83-row Balance Sheet), that one vector's relevance to any single line
  item is diluted across dozens of unrelated rows. Two early approaches
  didn't work: (1) condensed dense-embedding text (strip note/page
  reference codes) — no meaningful difference, dilution comes from the
  other ~80 unrelated rows, not reference-code noise. (2) Row-level
  auxiliary *dense-only* vectors using bare spreadsheet-fragment text
  (label + raw values, no sentence structure) — big improvement on bare
  keyword phrases (0.61 → 0.81 cosine) but no improvement on full
  natural-language questions (0.61 → 0.59), reverted.

  What worked: generating one natural-language sentence per row (label +
  values + section_title + fiscal_year, e.g. "In the BALANCE SHEET for
  FY2024-25 (tata-steel-fy2025.pdf), Property, plant and equipment was
  93,203.83 as at March 31, 2025, compared to ...") and indexing it as
  both a dense **and** sparse vector on its own child chunk
  (`chunk_type="table_row"`), alongside the existing whole-table chunk —
  confirmed via cheap cosine comparison before indexing (0.79 vs. the
  0.61 baseline and 0.59 failed attempt) and validated live post-index.
  Two data-quality gates were added on top, both confirmed necessary on
  real data: a table-level gate skips row-chunking entirely for a table
  where >30% of rows would produce an empty/near-empty/dash-only label
  (`LARGE_TABLE_LABEL_QUALITY_THRESHOLD` in `config.py`), and a per-row
  filter additionally drops individually poor-labeled rows even inside an
  otherwise-accepted table.

  **Net result, tested against 4 independently-chosen real facts spanning
  multiple tables and documents: 3 of 4 now retrieve and answer
  correctly** (Capital work-in-progress FY2024-25, Finance costs
  FY2024-25, and Property/Plant/Equipment as at March 31, 2022 — a
  different fiscal year's filing entirely). **One case remains a known,
  precisely-diagnosed exception**: Property, Plant and Equipment as at
  March 31, 2025 specifically, blocked by the FY2025 filing's Note 3 PP&E
  reconciliation schedule, which produces two garbage patterns the
  quality gates don't catch — (a) a "Title Deeds not available"
  sub-table's column-misalignment fragments (real text, ≥3 characters, so
  not flagged as poor, but semantically nonsensical after extraction),
  and (b) rows with more than 3 value columns (spanning up to 7 fiscal
  years), which breaks the sentence generator's current/prior/prior-prior
  date-arithmetic assumption. Deliberately not chased further: fixing the
  first garbage mode (dash-only labels) immediately surfaced these two
  different ones — the signature of diminishing returns on one
  adversarial table, not a sign the general approach doesn't work. See
  `tests/acceptance_criteria_day2.md` criterion 1 (now tested against a
  passing case) and `DEMO_REFERENCE.md` (flags this specific query to
  avoid live).

- **Gemini free-tier daily request quota (~20/day/model).** A live 429
  from `gemini-3.6-flash` reported `quotaId:
  GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue: 20` —
  confirmed via testing to be a genuine per-day cap, not a per-minute one:
  waited 30s and retried, still 429 (a per-minute/rolling limit would have
  recovered by then). A separate, different error ("prepayment credits are
  depleted," pointing at Gemini's billing/prepay docs) also surfaced later
  the same evening — not investigated further and not resolved tonight;
  not proceeding with paid billing for now. The free-tier daily cap above
  is the constraint to plan demo pacing around until/unless that changes.
  `gemini-2.5-flash` and `gemini-2.0-flash` were checked live as potential
  higher-quota fallbacks and are both hard-404 "no longer available" for
  this project's API key — `gemini-3.6-flash` remains the only working
  option, so this is a pacing constraint, not something to switch away
  from.


  ## Day 3 additions

- **Frontend**: React + Tailwind. Login page, chat interface (upload +
  ask + citations), protected routes (redirect to login if unauthenticated).
- **Auth**: username/password. Passwords hashed (bcrypt/passlib). JWT
  access tokens issued on login, required on /ask and /upload. Users
  stored in a small SQLite table (separate from query_log.db or a
  separate table in it — decide at implementation). No email verification,
  no password reset flow — out of scope for a 1-day interview demo.
  Simple signup endpoint (no invite/approval flow).
- **Upload — real ingestion wiring**: POST /upload (authenticated) now
  runs the actual pipeline: parse the uploaded PDF (reuse pdf_parser.py),
  chunk it (chunker.py), re-fit BM25 across the WHOLE corpus (existing +
  new file — BM25 vocab is global, per the Day 1 note in
  sparse_vectorizer.py), re-embed only the new chunks, upsert into Qdrant.
  Runs synchronously for now (no background job queue) — acceptable given
  demo-scale document counts, but the request will block until ingestion
  completes (could be several minutes for a large PDF).
- **Deployment**: Docker Compose — qdrant + backend (FastAPI) + frontend
  (React) as separate services, one `docker compose up`.
- **Time-box**: auth implementation gets ~1 hour before falling back to a
  simpler shared-secret gate if it's not working cleanly.
  
  ## Email verification (added post-Day-3)

- Users must verify their email before their account is usable (or
  before /ask works -- decide scope: block login entirely, or allow
  login but block /ask/upload until verified -- default: block login).
- Email sending via Resend (RESEND_API_KEY env var, same fail-fast
  startup check pattern as JWT_SECRET_KEY).
- Signup requires an email field (not just username) going forward.
- Verification: a random token generated at signup, emailed as a link
  (e.g. /verify?token=...), stored in the users table with an
  `is_verified` boolean and `verification_token` column.
- Existing users created before this feature: treated as already
  verified (no forced re-verification) -- migration-safe like the Day 3
  username column addition.