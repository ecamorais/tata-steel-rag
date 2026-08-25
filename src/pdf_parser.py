import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

# Real financial tables in these reports are compact, ruled, and mostly
# filled. pdfplumber's line-based table finder also flags decorative
# borders/icons (tiny slivers) and full-page layout backgrounds (near
# page-sized, sparsely filled) as "tables" — these thresholds filter those
# false positives out.
MIN_TABLE_ROWS = 2
MIN_TABLE_COLS = 2
MIN_TABLE_NONEMPTY_CELLS = 4
MIN_TABLE_FILL_RATIO = 0.4
MAX_TABLE_PAGE_AREA_RATIO = 0.4

# The headline statements (Balance Sheet, P&L) have no ruling lines at
# all, so line-based detection misses them entirely. When a page has no
# ruled table, fall back to pdfplumber's text-alignment strategy — but
# that strategy treats *any* page as one big "table" (whitespace gaps in
# justified prose look like column boundaries too), so it needs its own
# gate: real financial statements are 25-39% pure-numeric cells in
# practice, vs 1-11% for narrative pages caught by the same strategy.
# Area-ratio doesn't work as a filter here (a genuine multi-page-spanning
# statement legitimately covers most of the page), so this path skips it
# and relies on the numeric-cell fraction instead.
TEXT_STRATEGY_MIN_FILL_RATIO = 0.15
MIN_TABLE_NUMERIC_FRACTION = 0.15
_NUMERIC_CELL_RE = re.compile(r"^[\d,.\-()%\s]+$")

# A line counts as a heading if its font is notably larger than the
# document's body text size and it's short enough to plausibly be a
# heading rather than a wrapped paragraph line.
HEADING_SIZE_RATIO = 1.15
HEADING_MAX_WORDS = 12

# Some wide disclosure tables (e.g. related-party/subsidiary listings) are
# drawn sideways within an otherwise-portrait page via per-character
# rotation, not a page-level /Rotate flag -- pdfplumber's 'upright' char
# flag catches this where page.rotation does not. Our line/table
# extraction assumes horizontal reading order, which turns rotated text
# into scrambled, unusable output rather than just messy output. Verified
# on real data: normal pages run 100% upright; affected pages run 1-4%.
# Skipped entirely (no table, no prose) rather than indexed as corrupted
# text -- a deliberate, documented content gap on a small number of pages.
MIN_UPRIGHT_CHAR_FRACTION = 0.5


@dataclass
class TableBlock:
    page_number: int
    section_title: str | None
    rows: list[list[str | None]]


@dataclass
class ProseBlock:
    page_number: int
    section_title: str | None
    text: str


def _point_in_bbox(x: float, y: float, bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    return x0 <= x <= x1 and top <= y <= bottom


def _char_outside_tables(obj: dict, table_bboxes: list[tuple[float, float, float, float]]) -> bool:
    if obj.get("object_type") != "char":
        return True
    x = (obj["x0"] + obj["x1"]) / 2
    y = (obj["top"] + obj["bottom"]) / 2
    return not any(_point_in_bbox(x, y, bbox) for bbox in table_bboxes)


def _numeric_cell_fraction(rows: list[list[str | None]]) -> float:
    nonempty = [c.strip() for r in rows for c in r if c and c.strip()]
    if not nonempty:
        return 0.0
    numeric = sum(1 for c in nonempty if _NUMERIC_CELL_RE.match(c))
    return numeric / len(nonempty)


def _table_shape_ok(rows: list[list[str | None]], min_fill_ratio: float) -> bool:
    if len(rows) < MIN_TABLE_ROWS or not rows or len(rows[0]) < MIN_TABLE_COLS:
        return False
    total_cells = sum(len(r) for r in rows)
    nonempty_cells = sum(1 for r in rows for c in r if c and c.strip())
    if nonempty_cells < MIN_TABLE_NONEMPTY_CELLS:
        return False
    return not (total_cells and nonempty_cells / total_cells < min_fill_ratio)


def _is_real_ruled_table(rows: list[list[str | None]], bbox: tuple[float, float, float, float], page_area: float) -> bool:
    if not _table_shape_ok(rows, MIN_TABLE_FILL_RATIO):
        return False
    x0, top, x1, bottom = bbox
    area = max(x1 - x0, 0) * max(bottom - top, 0)
    return not (page_area and area / page_area > MAX_TABLE_PAGE_AREA_RATIO)


def _is_real_borderless_table(rows: list[list[str | None]]) -> bool:
    if not _table_shape_ok(rows, TEXT_STRATEGY_MIN_FILL_RATIO):
        return False
    return _numeric_cell_fraction(rows) >= MIN_TABLE_NUMERIC_FRACTION


def _extract_page_tables(page, page_area: float) -> list[tuple[tuple[float, float, float, float], list[list[str | None]]]]:
    accepted = []
    for table in page.find_tables():
        rows = table.extract()
        if _is_real_ruled_table(rows, table.bbox, page_area):
            accepted.append((table.bbox, rows))
    if accepted:
        return accepted

    # No ruled tables on this page — try text-alignment detection instead,
    # gated by _is_real_borderless_table so narrative pages (which this
    # strategy also flags as one big "table") get rejected. Only attempted
    # as a fallback (not merged with ruled results) because on a page that
    # mixes prose with a real ruled table, this strategy tends to glue the
    # two together into one blob.
    text_settings = {"vertical_strategy": "text", "horizontal_strategy": "text"}
    for table in page.find_tables(table_settings=text_settings):
        rows = table.extract()
        if _is_real_borderless_table(rows):
            accepted.append((table.bbox, rows))
    return accepted


def _line_font_size(line: dict) -> float:
    sizes = [c["size"] for c in line["chars"]]
    return statistics.mean(sizes) if sizes else 0.0


def parse_pdf(path: str | Path) -> list[TableBlock | ProseBlock]:
    """Parse a PDF into an ordered list of table/prose blocks.

    Single pass over the PDF (pages are expensive to re-walk): collects
    per-page lines, tables, and a document-wide font-size histogram at the
    same time. Heading classification needs the *global* body font size,
    so it happens in a second, cheap in-memory pass over the already
    extracted lines/tables rather than re-parsing the PDF.
    """
    path = Path(path)
    page_events: list[tuple[int, list[tuple]]] = []
    size_counts: Counter = Counter()

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            chars = page.chars
            if chars:
                upright_fraction = sum(1 for c in chars if c.get("upright")) / len(chars)
                if upright_fraction < MIN_UPRIGHT_CHAR_FRACTION:
                    continue

            page_area = page.width * page.height

            accepted_tables = _extract_page_tables(page, page_area)
            table_bboxes = [bbox for bbox, _ in accepted_tables]

            for char in page.chars:
                size_counts[round(char["size"], 1)] += 1

            prose_page = page.filter(lambda obj: _char_outside_tables(obj, table_bboxes))
            lines = prose_page.extract_text_lines()

            events = [
                ("line", line["top"], line["text"].strip(), _line_font_size(line))
                for line in lines
            ]
            events += [("table", bbox[1], rows) for bbox, rows in accepted_tables]
            events.sort(key=lambda e: e[1])

            page_events.append((page.page_number, events))

    body_size = size_counts.most_common(1)[0][0] if size_counts else 10.0
    heading_threshold = body_size * HEADING_SIZE_RATIO

    blocks: list[TableBlock | ProseBlock] = []
    current_section_title: str | None = None

    for page_number, events in page_events:
        paragraph_lines: list[str] = []

        def flush_paragraph() -> None:
            if paragraph_lines:
                text = " ".join(paragraph_lines).strip()
                if text:
                    blocks.append(ProseBlock(page_number, current_section_title, text))
                paragraph_lines.clear()

        for event in events:
            if event[0] == "line":
                _, _, text, size = event
                if not text:
                    flush_paragraph()
                    continue
                if size >= heading_threshold and len(text.split()) <= HEADING_MAX_WORDS:
                    flush_paragraph()
                    current_section_title = text
                    continue
                paragraph_lines.append(text)
            else:
                _, _, rows = event
                flush_paragraph()
                blocks.append(TableBlock(page_number, current_section_title, rows))

        flush_paragraph()

    return blocks
