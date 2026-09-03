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

- **Large-table retrieval gap (unresolved).** A table chunk gets a single
  dense + sparse vector for its entire content; for a large table (e.g.
  the 83-row Balance Sheet), that one vector's relevance to any single
  line item is diluted across dozens of unrelated rows, so a natural-
  language question about one specific figure (e.g. Property, Plant and
  Equipment) doesn't retrieve it even at top 60. Tried: (1) table
  cell-merge fix for word-wrapped labels — worked, kept (`chunker.py`).
  (2) Condensed dense-embedding text (strip note/page reference codes) —
  tested, made no meaningful difference (dilution comes from the other
  ~80 unrelated rows, not reference-code noise). (3) Row-level auxiliary
  dense vectors (one extra vector per row, sharing the parent chunk's
  payload/citation) — tested, big improvement on bare keyword phrases
  (0.61 → 0.81 cosine) but no improvement on full natural-language
  questions (0.61 → 0.59), so reverted. Currently an accepted, documented
  limitation (see `tests/acceptance_criteria_day2.md` criterion 1) and a
  candidate for future work, not a Day 2 blocker.

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