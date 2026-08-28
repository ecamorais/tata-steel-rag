import numpy as np
from qdrant_client.models import (
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Prefetch,
)

from src.config import BM25_VECTORIZER_PATH, COLLECTION_NAME, DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME
from src.embeddings import encode_query
from src.indexer import get_client
from src.sparse_vectorizer import BM25SparseVectorizer

_vectorizer: BM25SparseVectorizer | None = None


def _get_vectorizer() -> BM25SparseVectorizer:
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = BM25SparseVectorizer.load(BM25_VECTORIZER_PATH)
    return _vectorizer


def reset_vectorizer_cache() -> None:
    """Forces the next hybrid_search() call to reload bm25_vectorizer.json
    from disk. Must be called after upload_ingest.py refits BM25 -- without
    it, a long-running server process that already served one /ask (which
    populates the cache above) would keep scoring against the stale
    pre-upload vocab for every subsequent /ask, silently missing terms
    from the newly uploaded file until the process restarts."""
    global _vectorizer
    _vectorizer = None


def hybrid_search(query: str, top_k: int = 5, fiscal_year: str | None = None) -> list[dict]:
    client = get_client()
    vectorizer = _get_vectorizer()

    dense_query_vec = encode_query(query)
    sparse_query_vec = vectorizer.query_vector(query)

    year_filter = None
    if fiscal_year is not None:
        year_filter = Filter(must=[FieldCondition(key="fiscal_year", match=MatchValue(value=fiscal_year))])

    # Over-fetch per prefetch so RRF has real candidates to fuse across
    # dense/sparse, not just two top_k lists concatenated.
    prefetch_limit = max(top_k * 4, 20)

    fused = client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(
                query=dense_query_vec.tolist(),
                using=DENSE_VECTOR_NAME,
                limit=prefetch_limit,
                filter=year_filter,
            ),
            Prefetch(
                query=sparse_query_vec,
                using=SPARSE_VECTOR_NAME,
                limit=prefetch_limit,
                filter=year_filter,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        query_filter=year_filter,
        limit=top_k,
        with_payload=True,
    ).points

    if not fused:
        return []

    # RRF's score is rank-based (1/(k+rank)) and looks similar in
    # magnitude regardless of whether results are actually relevant -- an
    # ANN search always returns *a* top-k. Raw dense cosine similarity is
    # what actually drops for irrelevant queries, so it's computed
    # directly from each hit's own stored vector (not looked up from a
    # separate top-k dense query, which could miss a hit that only
    # surfaced via the sparse side).
    ids = [pt.id for pt in fused]
    retrieved = client.retrieve(collection_name=COLLECTION_NAME, ids=ids, with_vectors=True)
    dense_vec_by_id = {pt.id: np.array(pt.vector[DENSE_VECTOR_NAME]) for pt in retrieved}

    hits = []
    for pt in fused:
        dense_vec = dense_vec_by_id.get(pt.id)
        cosine = float(np.dot(dense_vec, dense_query_vec)) if dense_vec is not None else None
        hits.append(
            {
                "chunk_id": pt.id,
                "rrf_score": pt.score,
                "dense_cosine": cosine,
                **pt.payload,
            }
        )
    return hits
