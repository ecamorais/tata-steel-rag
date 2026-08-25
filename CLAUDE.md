# CLAUDE.md

## Project overview

RAG (Retrieval-Augmented Generation) system built over Tata Steel's last
three annual reports (FY2023, FY2024, FY2025). This is a hands-on demo
project built for an interview — prioritize a working, explainable pipeline
over production hardening.

## Stack decisions

- **PDF parsing**: `pdfplumber`
- **Chunking**: structural chunking — chunks follow document structure
  (sections/headings), not fixed-size windows
- **Vector store**: Qdrant, run via Docker, accessed at `localhost:6333`
- **Retrieval**: native Qdrant hybrid search — dense + sparse vectors in the
  same collection, fused with **RRF (Reciprocal Rank Fusion)**
- **Embeddings**: `sentence-transformers`, model `bge-small-en-v1.5`

## Project structure

- `data/raw/` — source PDFs (the 3 annual reports)
- `data/processed/` — parsed/chunked output
- `src/` — application code (parsing, chunking, indexing, retrieval)
- `tests/` — tests

## Conventions

- **Chunk metadata schema** — every chunk carries:
  - `source_file`
  - `fiscal_year`
  - `page_number`
  - `section_title`
  - `chunk_type`
- **Never split a table across chunks.** A table is kept whole in a single
  chunk even if that makes the chunk larger than the target size.

## Workflow constraint

- Always propose a plan and wait for explicit approval before writing any
  code.
- Implement **one file at a time**. After each file, pause for a diff
  review before moving to the next file.
