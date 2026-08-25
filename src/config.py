import re
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

CHUNKS_PATH = PROCESSED_DIR / "chunks.jsonl"
BM25_VECTORIZER_PATH = PROCESSED_DIR / "bm25_vectorizer.json"

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "tata_steel_reports"
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

PROSE_CHUNK_MIN_WORDS = 250
PROSE_CHUNK_MAX_WORDS = 400

# Fixed namespace for deriving deterministic per-chunk point IDs (uuid5),
# so re-ingesting unchanged PDFs upserts the same points instead of
# creating duplicates.
POINT_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "tata-steel-rag")

_FY_PATTERN = re.compile(r"fy(\d{4})", re.IGNORECASE)


def fiscal_year_from_filename(path: str | Path) -> str:
    """tata-steel-fy2023.pdf -> "FY2022-23" (Indian FY: April Y-1 - March Y)."""
    name = Path(path).name
    match = _FY_PATTERN.search(name)
    if not match:
        raise ValueError(f"Could not find a fyYYYY pattern in filename: {name!r}")
    end_year = int(match.group(1))
    start_year = end_year - 1
    return f"FY{start_year}-{str(end_year)[2:]}"
