import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import (
    POINT_ID_NAMESPACE,
    PROSE_CHUNK_MAX_WORDS,
    PROSE_CHUNK_MIN_WORDS,
    fiscal_year_from_filename,
)
from src.pdf_parser import ProseBlock, TableBlock

# ProseBlocks from pdf_parser.py are "all body text between two headings",
# not individual paragraphs — this PDF has no blank-line paragraph markers,
# so a block is often several paragraphs long (median ~490 words on a
# sample section). Sentence boundaries are the reliable structural unit
# available; chunks are grouped sentences, never cut mid-sentence.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

# Fragments below this are noise, not content — running headers, stray
# punctuation, and other leakage from pdf_parser.py's known heading- and
# borderless-table-detection limitations end up as isolated tiny blocks
# with nothing to merge into. This is well below the 250-400 word target
# band (a merge floor for otherwise-legitimate short sections); it only
# catches fragments too small to be useful regardless of target size.
MIN_VIABLE_PROSE_WORDS = 4


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source_file: str
    fiscal_year: str
    page_number: int
    section_title: str | None
    chunk_type: str
    chunk_index: int


def _make_chunk_id(source_file: str, page_number: int, chunk_index: int) -> str:
    return str(uuid.uuid5(POINT_ID_NAMESPACE, f"{source_file}:{page_number}:{chunk_index}"))


def _serialize_table(rows: list[list[str | None]]) -> str:
    """One line per row, blank cells dropped (word-wrap artifacts split a
    single label across several cells with no content in between — keeping
    those as empty fields would just add noise)."""
    lines = []
    for row in rows:
        cells = [c.strip() for c in row if c and c.strip()]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def _group_sentences(sentences: list[str], min_words: int, max_words: int) -> list[str]:
    groups: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())
        if current and current_words + sentence_words > max_words:
            groups.append(" ".join(current))
            current = []
            current_words = 0
        current.append(sentence)
        current_words += sentence_words
    if current:
        groups.append(" ".join(current))

    # min_words is a merge floor, not a split trigger: fold an
    # undersized group into the previous one rather than emitting a
    # tiny fragment. Never merges across a heading boundary since this
    # runs on the sentences of a single ProseBlock.
    merged: list[str] = []
    for group in groups:
        if merged and len(group.split()) < min_words:
            merged[-1] = f"{merged[-1]} {group}"
        else:
            merged.append(group)
    return merged


def chunk_blocks(blocks: list[TableBlock | ProseBlock], source_path: str | Path) -> list[Chunk]:
    source_path = Path(source_path)
    source_file = source_path.name
    fiscal_year = fiscal_year_from_filename(source_path)

    chunks: list[Chunk] = []
    index = 0

    for block in blocks:
        if isinstance(block, TableBlock):
            text = _serialize_table(block.rows)
            if not text:
                continue
            chunks.append(
                Chunk(
                    chunk_id=_make_chunk_id(source_file, block.page_number, index),
                    text=text,
                    source_file=source_file,
                    fiscal_year=fiscal_year,
                    page_number=block.page_number,
                    section_title=block.section_title,
                    chunk_type="table",
                    chunk_index=index,
                )
            )
            index += 1
        else:
            sentences = _split_sentences(block.text)
            if not sentences:
                continue
            for group_text in _group_sentences(sentences, PROSE_CHUNK_MIN_WORDS, PROSE_CHUNK_MAX_WORDS):
                if len(group_text.split()) < MIN_VIABLE_PROSE_WORDS:
                    continue
                chunks.append(
                    Chunk(
                        chunk_id=_make_chunk_id(source_file, block.page_number, index),
                        text=group_text,
                        source_file=source_file,
                        fiscal_year=fiscal_year,
                        page_number=block.page_number,
                        section_title=block.section_title,
                        chunk_type="prose",
                        chunk_index=index,
                    )
                )
                index += 1

    return chunks


def write_chunks_jsonl(chunks: list[Chunk], path: str | Path, mode: str = "w") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
