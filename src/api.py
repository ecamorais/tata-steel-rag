from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.config import GENERATION_TOP_K, UPLOADS_DIR
from src.generator import generate_answer
from src.indexer import check_qdrant_reachable
from src.logging_store import init_db, log_call
from src.prompt import build_user_content
from src.retriever import hybrid_search


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Qdrant/Docker has dropped silently mid-session multiple times during
    # development -- fail loudly at startup rather than let the first
    # /ask request hit a raw connection-refused stack trace.
    check_qdrant_reachable()
    yield


app = FastAPI(title="Tata Steel RAG", lifespan=lifespan)
init_db()


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
def ask(request: AskRequest) -> AskResponse:
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
async def upload(file: UploadFile = File(...)):
    is_pdf = (file.content_type == "application/pdf") or (file.filename or "").lower().endswith(".pdf")
    if not is_pdf:
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    (UPLOADS_DIR / file.filename).write_bytes(content)

    raise HTTPException(
        status_code=501,
        detail={
            "status": "not_implemented",
            "message": (
                "File received and saved, but full ingestion (parse, chunk, embed, index) "
                "is not implemented yet -- coming in Day 3."
            ),
            "filename": file.filename,
        },
    )
