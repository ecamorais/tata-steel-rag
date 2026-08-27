import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, SparseVector, SparseVectorParams, VectorParams

from src.chunker import Chunk
from src.config import COLLECTION_NAME, DENSE_VECTOR_NAME, EMBEDDING_DIM, QDRANT_HOST, QDRANT_PORT, SPARSE_VECTOR_NAME


def get_client() -> QdrantClient:
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def check_qdrant_reachable(timeout: float = 3.0) -> None:
    """Qdrant/Docker has dropped silently mid-session multiple times during
    development -- without this, the first symptom is a raw httpx/httpcore
    connection-refused stack trace many frames deep in query_points() or
    upsert(). Fails fast with an obvious, actionable message instead. Uses
    its own short-timeout client rather than get_client()'s default, so a
    real slow-but-alive server elsewhere isn't penalized by this check."""
    probe_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=timeout)
    try:
        probe_client.get_collections()
    except Exception as e:
        raise RuntimeError(
            f"Qdrant is unreachable at {QDRANT_HOST}:{QDRANT_PORT}. "
            f"Check Docker is running and the Qdrant container is up "
            f"(`docker ps`, `docker start <container>`). "
            f"Original error: {type(e).__name__}: {e}"
        ) from e


def ensure_collection(client: QdrantClient) -> None:
    # Only creates when missing — never drops/recreates an existing
    # collection. Recreating on every ingest run would make re-ingestion
    # trivially "idempotent" (wipe + rebuild always gives the same count)
    # without actually exercising upsert's dedup-by-id behavior.
    if client.collection_exists(COLLECTION_NAME):
        return
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={DENSE_VECTOR_NAME: VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE)},
        sparse_vectors_config={SPARSE_VECTOR_NAME: SparseVectorParams()},
    )


def upsert_chunks(
    client: QdrantClient,
    chunks: list[Chunk],
    dense_vecs: np.ndarray,
    sparse_vecs: list[SparseVector],
    batch_size: int = 256,
) -> None:
    total = len(chunks)
    num_batches = (total + batch_size - 1) // batch_size

    for batch_num, start in enumerate(range(0, total, batch_size), start=1):
        end = min(start + batch_size, total)
        points = [
            PointStruct(
                id=chunks[i].chunk_id,
                vector={
                    DENSE_VECTOR_NAME: dense_vecs[i].tolist(),
                    SPARSE_VECTOR_NAME: sparse_vecs[i],
                },
                payload={
                    "source_file": chunks[i].source_file,
                    "fiscal_year": chunks[i].fiscal_year,
                    "page_number": chunks[i].page_number,
                    "section_title": chunks[i].section_title,
                    "chunk_type": chunks[i].chunk_type,
                    "text": chunks[i].text,
                },
            )
            for i in range(start, end)
        ]
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"  upserted batch {batch_num}/{num_batches} ({end}/{total} points)")


def get_point_count(client: QdrantClient) -> int:
    return client.count(collection_name=COLLECTION_NAME, exact=True).count
