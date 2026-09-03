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
