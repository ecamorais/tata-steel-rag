from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from google.genai.errors import ClientError, ServerError
from pydantic import BaseModel, EmailStr, Field

from src.auth import check_jwt_secret_configured, create_access_token, get_current_user, hash_password, verify_password
from src.config import FRONTEND_BASE_URL, GENERATION_TOP_K, UPLOADS_DIR
from src.email_verification import check_resend_configured, generate_verification_token, send_verification_email
from src.generator import generate_answer
from src.indexer import check_qdrant_reachable, ensure_fiscal_year_index, get_client
from src.intent import detect_comparison_intent
from src.logging_store import get_calls_by_username, init_db, log_call
from src.prompt import build_comparison_user_content, build_user_content
from src.retriever import compare_across_documents, hybrid_search
from src.upload_ingest import ingest_uploaded_pdf
from src.users_store import (
    create_user,
    get_user_by_username,
    get_user_by_verification_token,
    init_users_table,
    mark_user_verified,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Qdrant/Docker has dropped silently mid-session multiple times during
    # development -- fail loudly at startup rather than let the first
    # /ask request hit a raw connection-refused stack trace. Same reasoning
    # for JWT_SECRET_KEY: fail at startup, not on the first login call.
    check_qdrant_reachable()
    ensure_fiscal_year_index(get_client())
    check_jwt_secret_configured()
    check_resend_configured()
    yield


app = FastAPI(title="Tata Steel RAG", lifespan=lifespan)

# Frontend runs on a different origin/port (Vite dev server, or a separate
# container in Docker Compose). No cookies are used -- auth is a Bearer
# token the frontend attaches itself -- so a wildcard origin carries no
# credential-leakage risk here, unlike allow_credentials=True would.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
init_users_table()


class SignupRequest(BaseModel):
    username: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)


class SignupResponse(BaseModel):
    username: str


@app.post("/signup", response_model=SignupResponse, status_code=201)
def signup(request: SignupRequest) -> SignupResponse:
    token = generate_verification_token()
    try:
        create_user(request.username, hash_password(request.password), str(request.email), token)
    except ValueError as e:
        # create_user raises ValueError on a duplicate username (see
        # users_store.py) -- 409 Conflict, not a 500.
        raise HTTPException(status_code=409, detail=str(e))

    try:
        send_verification_email(str(request.email), token)
    except Exception as e:
        # Fails loudly rather than silently leaving an account that can
        # never receive its verification link -- consistent with this
        # project's no-silent-failures pattern elsewhere (e.g. the
        # ingest_uploaded_pdf error handling in /upload).
        raise HTTPException(
            status_code=502,
            detail=f"Account created, but the verification email failed to send: {e}",
        )

    return SignupResponse(username=request.username)


@app.get("/verify")
def verify(token: str) -> RedirectResponse:
    user = get_user_by_verification_token(token)
    if user is None:
        return RedirectResponse(url=f"{FRONTEND_BASE_URL}/login?verified=false")
    mark_user_verified(user["id"])
    return RedirectResponse(url=f"{FRONTEND_BASE_URL}/login?verified=true")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.post("/login", response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
    user = get_user_by_username(request.username)
    # Password checked before is_verified: a wrong password always gets the
    # same generic message, so a login attempt can't be used to probe
    # whether an account exists but is simply unverified.
    if user is None or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user["is_verified"]:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in.")
    return LoginResponse(access_token=create_access_token(user["username"]))


class AskRequest(BaseModel):
    query: str = Field(min_length=1)
    fiscal_year: str | None = None
    compare: bool = False
    fiscal_years: list[str] | None = None


class CitationResponse(BaseModel):
    source_file: str
    page_number: int


class AskResponse(BaseModel):
    answer: str
    found: bool
    citations: list[CitationResponse]


GEMINI_BUSY_MESSAGE = "The AI service is temporarily busy, please try again in a moment."


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, user: dict = Depends(get_current_user)) -> AskResponse:
    is_comparison = request.compare or detect_comparison_intent(request.query)
    if is_comparison:
        chunks = compare_across_documents(request.query, fiscal_years=request.fiscal_years)
    else:
        chunks = hybrid_search(request.query, top_k=GENERATION_TOP_K, fiscal_year=request.fiscal_year)
    try:
        result = generate_answer(request.query, chunks, comparison_mode=is_comparison)
    except ClientError as e:
        if e.code == 429:
            # Free-tier Gemini rate limit -- confirmed live to otherwise
            # surface as an unhandled 500 with NO CORS headers (Starlette's
            # default error response bypasses CORSMiddleware), which a real
            # browser blocks outright and reports as "Failed to fetch" --
            # useless to whoever's using the app. A clean HTTPException
            # response does get CORS headers, so this actually fixes what
            # the browser shows, not just the wording.
            raise HTTPException(status_code=503, detail=GEMINI_BUSY_MESSAGE)
        raise
    except ServerError:
        # Any 5xx from Gemini (e.g. the real 503 "high demand" seen live
        # during testing) is the service's own transient trouble, not a
        # mistake in our request -- unlike ClientError, every ServerError
        # code is safe to treat as "busy, retry," not just one specific
        # code. Same CORS-header reasoning as the ClientError branch above.
        raise HTTPException(status_code=503, detail=GEMINI_BUSY_MESSAGE)
    except Exception:
        # Fallback for any Gemini-side failure that isn't a ClientError or
        # ServerError -- confirmed live during comparison-feature testing:
        # a network/timeout exception from the genai SDK crashed as a bare
        # unhandled 500 with no CORS headers, the exact "Failed to fetch"
        # browser symptom the two handlers above were already built to
        # avoid. Degrading any such failure to the same clean "busy"
        # message is strictly better than an unhandled crash, even though
        # it's not always literally a busy-retry situation.
        raise HTTPException(status_code=503, detail=GEMINI_BUSY_MESSAGE)

    # Cheap insurance against citing a page never actually shown to the
    # model: drop any citation that doesn't match a chunk we retrieved
    # (acceptance criterion 3 -- accurate, not just present).
    retrieved_keys = {(c["source_file"], c["page_number"]) for c in chunks}
    valid_citations = [c for c in result.citations if (c.source_file, c.page_number) in retrieved_keys]

    if is_comparison:
        prompt_text = build_comparison_user_content(request.query, chunks)
        fiscal_year_filter = ",".join(sorted({c["fiscal_year"] for c in chunks}))
    else:
        prompt_text = build_user_content(request.query, chunks)
        fiscal_year_filter = request.fiscal_year

    answer_payload = {
        "answer": result.answer,
        "found": result.found,
        "citations": [c.model_dump() for c in valid_citations],
    }
    log_call(
        query=request.query,
        fiscal_year_filter=fiscal_year_filter,
        retrieved_chunks=chunks,
        prompt_text=prompt_text,
        answer=answer_payload,
        username=user["username"],
        is_comparison=is_comparison,
    )

    return AskResponse(
        answer=result.answer,
        found=result.found,
        citations=[CitationResponse(source_file=c.source_file, page_number=c.page_number) for c in valid_citations],
    )


HISTORY_LIMIT = 50


class HistoryEntry(BaseModel):
    id: int
    timestamp: str
    query: str
    fiscal_year_filter: str | None
    answer: str
    found: bool
    citations: list[CitationResponse]


@app.get("/history", response_model=list[HistoryEntry])
def history(user: dict = Depends(get_current_user)) -> list[HistoryEntry]:
    calls = get_calls_by_username(user["username"], limit=HISTORY_LIMIT)
    return [
        HistoryEntry(
            id=call["id"],
            timestamp=call["timestamp"],
            query=call["query"],
            fiscal_year_filter=call["fiscal_year_filter"],
            answer=call["answer"]["answer"],
            found=call["answer"]["found"],
            citations=[CitationResponse(**c) for c in call["answer"]["citations"]],
        )
        for call in calls
    ]


@app.post("/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    is_pdf = (file.content_type == "application/pdf") or (file.filename or "").lower().endswith(".pdf")
    if not is_pdf:
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    saved_path = UPLOADS_DIR / file.filename
    saved_path.write_bytes(content)

    # Runs synchronously (no background job queue) -- the request blocks
    # until parse/chunk/embed/index completes, per CLAUDE.md's Day 3 scope.
    try:
        result = ingest_uploaded_pdf(saved_path)
    except ValueError as e:
        # Bad filename convention (missing fyYYYY pattern) or a PDF with no
        # extractable content -- a clean 400, not a 500.
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "ingested",
        "source_file": result["source_file"],
        "chunks_added": result["chunks_added"],
        "chunks_replaced": result["chunks_replaced"],
        "total_chunks": result["total_chunks"],
        "total_points": result["total_points"],
    }
