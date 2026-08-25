import time

import pdfplumber

from src.chunker import Chunk, chunk_blocks, write_chunks_jsonl
from src.config import BM25_VECTORIZER_PATH, CHUNKS_PATH, RAW_DIR
from src.embeddings import encode_documents
from src.indexer import ensure_collection, get_client, get_point_count, upsert_chunks
from src.pdf_parser import parse_pdf
from src.sparse_vectorizer import BM25SparseVectorizer

PDF_FILES = [
    "tata-steel-fy2023.pdf",
    "tata-steel-fy2024.pdf",
    "tata-steel-fy2025.pdf",
]

# Rough expectation for a prose-heavy annual report with substantial
# tabular disclosures, based on samples checked during development.
# A sanity signal for eyeballing the logged total against page count
# (acceptance criterion 5) -- not a hard requirement.
EXPECTED_CHUNKS_PER_PAGE_LOW = 1.0
EXPECTED_CHUNKS_PER_PAGE_HIGH = 3.5


def run(filenames: list[str] | None = None) -> list[Chunk]:
    if filenames is None:
        filenames = PDF_FILES

    all_chunks: list[Chunk] = []
    total_pages = 0

    for filename in filenames:
        path = RAW_DIR / filename
        with pdfplumber.open(path) as pdf:
            num_pages = len(pdf.pages)

        print(f"Parsing {filename} ({num_pages} pages)...")
        t0 = time.time()
        blocks = parse_pdf(path)
        parse_elapsed = time.time() - t0

        chunks = chunk_blocks(blocks, path)
        all_chunks.extend(chunks)
        total_pages += num_pages

        table_chunks = sum(1 for c in chunks if c.chunk_type == "table")
        prose_chunks = sum(1 for c in chunks if c.chunk_type == "prose")
        print(
            f"  {filename}: {num_pages} pages -> {len(chunks)} chunks "
            f"({table_chunks} table, {prose_chunks} prose) in {parse_elapsed:.1f}s"
        )

    total_chunks = len(all_chunks)
    expected_low = int(total_pages * EXPECTED_CHUNKS_PER_PAGE_LOW)
    expected_high = int(total_pages * EXPECTED_CHUNKS_PER_PAGE_HIGH)
    in_band = expected_low <= total_chunks <= expected_high
    band_verdict = "within band" if in_band else "OUTSIDE BAND -- inspect chunks.jsonl before trusting the index"
    print(
        f"\nTotal: {total_pages} pages -> {total_chunks} chunks "
        f"(expected band {expected_low}-{expected_high} at "
        f"{EXPECTED_CHUNKS_PER_PAGE_LOW}-{EXPECTED_CHUNKS_PER_PAGE_HIGH} chunks/page): {band_verdict}"
    )

    print("\nFitting BM25 sparse vectorizer over full corpus...")
    vectorizer = BM25SparseVectorizer().fit([c.text for c in all_chunks])
    vectorizer.save(BM25_VECTORIZER_PATH)

    print(f"Embedding {total_chunks} chunks (dense)...")
    dense_vecs = encode_documents([c.text for c in all_chunks], batch_size=64, show_progress_bar=True)

    print("Computing sparse vectors...")
    sparse_vecs = [vectorizer.doc_vector(c.text) for c in all_chunks]

    print(f"Writing {CHUNKS_PATH}...")
    write_chunks_jsonl(all_chunks, CHUNKS_PATH)

    print("Indexing into Qdrant...")
    client = get_client()
    ensure_collection(client)
    upsert_chunks(client, all_chunks, dense_vecs, sparse_vecs)

    point_count = get_point_count(client)
    print(f"\nDone. Qdrant collection now has {point_count} points.")

    return all_chunks


if __name__ == "__main__":
    run()
