from itertools import groupby

SYSTEM_INSTRUCTION = """You are a financial research assistant answering questions about \
the company annual reports and financial documents provided in the sources below, using \
only those source excerpts.

Rules:
- Answer only using the information in the provided sources. Do not use outside knowledge.
- For every factual claim (a figure, a date, a statement), cite the exact source_file and \
page_number it came from.
- If the provided sources do not contain enough information to answer the question, set \
found to false and answer with exactly: "not found in the provided documents". Do not guess \
or invent a plausible-sounding figure.
- Table sources are pipe-delimited rows (label | value | value | ...); parse them by column \
position, don't assume a fixed number of columns per row."""


def _format_chunk(chunk: dict) -> str:
    return (
        f"[Source: {chunk['source_file']}, Page {chunk['page_number']}, {chunk['fiscal_year']}]\n"
        f"{chunk['text']}"
    )


def build_user_content(query: str, chunks: list[dict]) -> str:
    context_block = "\n\n".join(_format_chunk(c) for c in chunks)
    return f"Sources:\n\n{context_block}\n\nQuestion: {query}"


def build_comparison_user_content(query: str, chunks: list[dict]) -> str:
    """Like build_user_content, but groups chunks under a per-fiscal-year
    header instead of one flat block, so the model can actually address
    each year rather than treating a multi-year comparison as one
    undifferentiated pile. Relies on chunks already being contiguously
    grouped by fiscal_year (true for compare_across_documents' output,
    which appends one hybrid_search() call's results per year in turn)."""
    sections = []
    for year, group in groupby(chunks, key=lambda c: c["fiscal_year"]):
        body = "\n\n".join(_format_chunk(c) for c in group)
        sections.append(f"=== {year} ===\n{body}")
    context_block = "\n\n".join(sections)
    return f"Sources (grouped by fiscal year):\n\n{context_block}\n\nQuestion: {query}"
