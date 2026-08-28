# Acceptance Criteria — Day 3 (Auth, Real Upload, Frontend, Deployment)

## Auth
1. A new user can sign up with a username/password.
2. A signed-up user can log in and receive a valid token.
3. POST /ask and POST /upload reject requests with no token or an invalid
   token (401), not a 500 or silent bypass.
4. A logged-in user's token successfully authorizes /ask and /upload calls.

## Real Upload Ingestion
5. Uploading a new PDF via POST /upload (authenticated) actually parses,
   chunks, embeds, and indexes it — verify via a real /ask query that
   retrieves content ONLY present in the newly uploaded file.
6. BM25 is re-fit across the full corpus (existing 3 PDFs + the new
   upload) after an upload — verify the vocab/idf file changed and a
   keyword unique to the new PDF is retrievable via sparse search.
7. Re-uploading the same PDF twice does not duplicate chunks/points
   (idempotent, consistent with Day 1's ingestion guarantee).

## Frontend
8. Unauthenticated access to the chat interface redirects to login, not a
   broken/blank page.
9. A logged-in user can ask a question through the UI and see the answer
   with citations rendered (not raw JSON).
10. A logged-in user can upload a PDF through the UI and get a clear
    success/failure indication (not silent).

## Deployment
11. `docker compose up` (from a clean state, no manual setup beyond
    environment variables) starts Qdrant + backend + frontend, and the
    full flow (login → ask → get a cited answer) works end to end.

## Sign-off
Each item checked off with evidence (a real signup/login, a real
uploaded-then-retrieved fact, a real docker compose up log, a screenshot
or described UI behavior) — not just "the code runs without error."
