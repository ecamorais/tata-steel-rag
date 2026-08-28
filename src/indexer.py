import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    PointVectors,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

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


def delete_chunks_by_source_file(client: QdrantClient, source_file: str) -> int:
    """Deletes every point for a given source_file -- used before
    re-inserting an uploaded PDF's chunks, so a re-upload replaces the old
    point set outright rather than relying solely on chunk_id determinism
    to avoid orphans (e.g. if a later chunking pass produces a different
    number of chunks for the same file)."""
    source_filter = Filter(must=[FieldCondition(key="source_file", match=MatchValue(value=source_file))])
    matched = client.count(collection_name=COLLECTION_NAME, count_filter=source_filter, exact=True).count
    if matched:
        client.delete(collection_name=COLLECTION_NAME, points_selector=FilterSelector(filter=source_filter))
    return matched


def update_sparse_vectors(
    client: QdrantClient,
    chunks: list[Chunk],
    sparse_vecs: list[SparseVector],
    batch_size: int = 256,
) -> None:
    """Updates ONLY the sparse vector on already-indexed points, leaving
    their dense vector and payload untouched -- confirmed live against a
    throwaway collection before this was written (update_vectors with a
    partial {SPARSE_VECTOR_NAME: ...} dict does not clear the other named
    vector). Needed after a BM25 refit: every existing chunk's sparse
    vector shifts because the global vocab/idf changed, but its dense
    embedding is still valid and re-embedding it would be pure waste.

    A chunk whose text tokenizes to nothing (e.g. pure parsing-noise
    fragments like "* # ^ *" -- confirmed to exist in the real corpus, 4
    of them) gets an empty SparseVector(indices=[], values=[]). Qdrant's
    upsert() accepts that fine on insert, but update_vectors() rejects an
    empty vector outright ("must specify vectors to update for point") --
    discovered by running this live against the real corpus. Skipped here:
    an empty vector was already empty before the refit, so there is
    nothing to update."""
    total = len(chunks)
    num_batches = (total + batch_size - 1) // batch_size

    for batch_num, start in enumerate(range(0, total, batch_size), start=1):
        end = min(start + batch_size, total)
        points = [
            PointVectors(id=chunks[i].chunk_id, vector={SPARSE_VECTOR_NAME: sparse_vecs[i]})
            for i in range(start, end)
            if sparse_vecs[i].indices
        ]
        if points:
            client.update_vectors(collection_name=COLLECTION_NAME, points=points)
        print(f"  updated sparse vectors: batch {batch_num}/{num_batches} ({end}/{total} points)")
