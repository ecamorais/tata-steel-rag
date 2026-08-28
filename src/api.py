from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.auth import check_jwt_secret_configured, create_access_token, get_current_user, hash_password, verify_password
from src.config import GENERATION_TOP_K, UPLOADS_DIR
from src.generator import generate_answer
from src.indexer import check_qdrant_reachable
from src.logging_store import init_db, log_call
from src.prompt import build_user_content
from src.retriever import hybrid_search
from src.upload_ingest import ingest_uploaded_pdf
from src.users_store import create_user, get_user_by_username, init_users_table


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Qdrant/Docker has dropped silently mid-session multiple times during
    # development -- fail loudly at startup rather than let the first
    # /ask request hit a raw connection-refused stack trace. Same reasoning
    # for JWT_SECRET_KEY: fail at startup, not on the first login call.
    check_qdrant_reachable()
    check_jwt_secret_configured()
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
    password: str = Field(min_length=8)


class SignupResponse(BaseModel):
    username: str


@app.post("/signup", response_model=SignupResponse, status_code=201)
def signup(request: SignupRequest) -> SignupResponse:
    try:
        create_user(request.username, hash_password(request.password))
    except ValueError as e:
        # create_user raises ValueError on a duplicate username (see
        # users_store.py) -- 409 Conflict, not a 500.
        raise HTTPException(status_code=409, detail=str(e))
    return SignupResponse(username=request.username)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.post("/login", response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
    user = get_user_by_username(request.username)
    if user is None or not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return LoginResponse(access_token=create_access_token(user["username"]))


class AskRequest(BaseModel):
    query: str = Field(min_length=1)
    fiscal_year: str | None = None


class CitationResponse(BaseModel):
    source_file: str
    page_number: int


class AskResponse(BaseModel):
    answer: str
    found: bool
    citations: list[CitationResponse]


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, user: dict = Depends(get_current_user)) -> AskResponse:
    chunks = hybrid_search(request.query, top_k=GENERATION_TOP_K, fiscal_year=request.fiscal_year)
    result = generate_answer(request.query, chunks)

    # Cheap insurance against citing a page never actually shown to the
    # model: drop any citation that doesn't match a chunk we retrieved
    # (acceptance criterion 3 -- accurate, not just present).
    retrieved_keys = {(c["source_file"], c["page_number"]) for c in chunks}
    valid_citations = [c for c in result.citations if (c.source_file, c.page_number) in retrieved_keys]

    prompt_text = build_user_content(request.query, chunks)
    answer_payload = {
        "answer": result.answer,
        "found": result.found,
        "citations": [c.model_dump() for c in valid_citations],
    }
    log_call(
        query=request.query,
        fiscal_year_filter=request.fiscal_year,
        retrieved_chunks=chunks,
        prompt_text=prompt_text,
        answer=answer_payload,
    )

    return AskResponse(
        answer=result.answer,
        found=result.found,
        citations=[CitationResponse(source_file=c.source_file, page_number=c.page_number) for c in valid_citations],
    )


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
