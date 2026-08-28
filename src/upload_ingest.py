from pathlib import Path

from src.chunker import chunk_blocks, read_chunks_jsonl, write_chunks_jsonl
from src.config import BM25_VECTORIZER_PATH, CHUNKS_PATH, fiscal_year_from_filename
from src.embeddings import encode_documents
from src.indexer import (
    delete_chunks_by_source_file,
    ensure_collection,
    get_client,
    get_point_count,
    update_sparse_vectors,
    upsert_chunks,
)
from src.pdf_parser import parse_pdf
from src.retriever import reset_vectorizer_cache
from src.sparse_vectorizer import BM25SparseVectorizer


def ingest_uploaded_pdf(path: str | Path) -> dict:
    """Incrementally ingests one uploaded PDF into the existing corpus.

    Per CLAUDE.md's Day 3 spec: BM25 is refit over the WHOLE corpus (its
    vocab/idf is global, per sparse_vectorizer.py's own Day 1 note), but
    only the new file's chunks get a dense (re-)embedding -- every other
    existing chunk's dense vector is still valid and untouched; only its
    sparse vector shifts because the vocab changed, so that's updated in
    place (validated live against a throwaway collection before this file
    was written: update_vectors on just the sparse key leaves dense alone).

    Idempotent: re-uploading the same source_file deletes-then-replaces its
    prior points and chunks.jsonl entries outright, rather than relying
    only on matching chunk_ids to avoid duplicates.
    """
    path = Path(path)
    source_file = path.name

    # Validate the fyYYYY filename convention before spending time parsing
    # a potentially large PDF -- surfaces as a fast, clean error (api.py
    # turns this into a 400) instead of failing deep inside chunk_blocks
    # after parsing has already run.
    fiscal_year_from_filename(source_file)

    blocks = parse_pdf(path)
    new_chunks = chunk_blocks(blocks, path)
    if not new_chunks:
        raise ValueError(f"No content could be extracted from {source_file!r}.")

    existing_chunks = read_chunks_jsonl(CHUNKS_PATH) if CHUNKS_PATH.exists() else []
    base_chunks = [c for c in existing_chunks if c.source_file != source_file]
    all_chunks = base_chunks + new_chunks

    vectorizer = BM25SparseVectorizer().fit([c.text for c in all_chunks])
    vectorizer.save(BM25_VECTORIZER_PATH)
    # retriever.py caches the loaded vectorizer for the life of the
    # process -- without this, a server that already served one /ask
    # before this upload would keep scoring against the stale pre-upload
    # vocab until restarted.
    reset_vectorizer_cache()

    base_sparse_vecs = [vectorizer.doc_vector(c.text) for c in base_chunks]
    new_sparse_vecs = [vectorizer.doc_vector(c.text) for c in new_chunks]
    new_dense_vecs = encode_documents([c.text for c in new_chunks])

    client = get_client()
    ensure_collection(client)
    replaced = delete_chunks_by_source_file(client, source_file)
    upsert_chunks(client, new_chunks, new_dense_vecs, new_sparse_vecs)
    if base_chunks:
        update_sparse_vectors(client, base_chunks, base_sparse_vecs)

    write_chunks_jsonl(all_chunks, CHUNKS_PATH, mode="w")

    return {
        "source_file": source_file,
        "chunks_added": len(new_chunks),
        "chunks_replaced": replaced,
        "total_chunks": len(all_chunks),
        "total_points": get_point_count(client),
    }
