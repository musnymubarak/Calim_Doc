"""Docling parsing. PDF/DOCX -> structured blocks (text + page + bbox + section path).

Each block carries provenance (page, bbox, section_path) and a char span into a canonical
`full_text` reconstruction. Tables are kept atomic (caption + body as one block). Consecutive
list items are tagged with a shared `list_group` so the chunker never splits them.

Docling is imported lazily so the API process (which never parses) doesn't need the heavy dep.
"""
from __future__ import annotations

from dataclasses import dataclass

# Docling label values we care about (compared as strings to tolerate version drift).
_HEADER_LABELS = {"section_header", "title"}
_TABLE_LABELS = {"table"}
_LIST_LABELS = {"list_item"}
_SKIP_LABELS = {"page_header", "page_footer"}


@dataclass
class ParsedBlock:
    text: str
    page: int
    bbox: list[dict]            # [{page, x0, y0, x1, y1}]
    section_path: str           # "4.2 > Indemnification"
    label: str
    char_start: int             # offset into ParsedDoc.full_text
    char_end: int
    is_table: bool = False
    list_group: str | None = None


@dataclass
class ParsedDoc:
    page_count: int
    blocks: list[ParsedBlock]
    full_text: str = ""         # canonical reconstruction; block char offsets index into this


def _label_of(item) -> str:
    label = getattr(item, "label", None)
    return str(getattr(label, "value", label) or "").lower()


def _provenance(item) -> tuple[int, list[dict]]:
    """Extract (page, bbox-list) from a Docling item's prov entries, defensively."""
    page: int | None = None
    bbox: list[dict] = []
    for prov in getattr(item, "prov", None) or []:
        pg = getattr(prov, "page_no", None)
        if page is None and pg is not None:
            page = pg
        bb = getattr(prov, "bbox", None)
        if bb is not None:
            bbox.append({
                "page": pg,
                "x0": getattr(bb, "l", None),
                "y0": getattr(bb, "t", None),
                "x1": getattr(bb, "r", None),
                "y1": getattr(bb, "b", None),
            })
    return (page or 1), bbox


def _table_text(item, doc) -> str:
    """Render a table to markdown, prefixed with its caption when available."""
    caption = ""
    try:
        caption = item.caption_text(doc) or ""
    except Exception:  # noqa: BLE001 — caption is best-effort
        caption = ""
    body = ""
    for attempt in (lambda: item.export_to_markdown(doc), lambda: item.export_to_markdown()):
        try:
            body = attempt()
            break
        except Exception:  # noqa: BLE001 — API arity varies by version
            continue
    return (f"{caption}\n{body}".strip()) if caption else body


def parse_document(file_path: str, mime_type: str) -> ParsedDoc:
    """Convert a document with Docling and flatten it into provenance-bearing blocks."""
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    doc = converter.convert(file_path).document

    blocks: list[ParsedBlock] = []
    parts: list[str] = []          # full_text pieces
    cursor = 0                     # running char offset into full_text
    heading_stack: list[tuple[int, str]] = []   # (level, text)
    list_counter = 0
    prev_was_list = False

    def section_path() -> str:
        return " > ".join(text for _, text in heading_stack)

    def append_block(text: str, page: int, bbox: list[dict], label: str,
                     *, is_table: bool = False, list_group: str | None = None) -> None:
        nonlocal cursor
        text = text.strip()
        if not text:
            return
        start = cursor
        parts.append(text)
        cursor += len(text)
        end = cursor
        parts.append("\n\n")       # separator (also advances the cursor below)
        cursor += 2
        blocks.append(ParsedBlock(
            text=text, page=page, bbox=bbox, section_path=section_path(),
            label=label, char_start=start, char_end=end,
            is_table=is_table, list_group=list_group,
        ))

    for item, level in doc.iterate_items():
        label = _label_of(item)
        if label in _SKIP_LABELS:
            prev_was_list = False
            continue

        page, bbox = _provenance(item)

        if label in _HEADER_LABELS:
            depth = int(getattr(item, "level", level) or level)
            text = (getattr(item, "text", "") or "").strip()
            # Pop sibling/deeper headings, then push this one.
            while heading_stack and heading_stack[-1][0] >= depth:
                heading_stack.pop()
            if text:
                heading_stack.append((depth, text))
                append_block(text, page, bbox, label)
            prev_was_list = False
            continue

        if label in _TABLE_LABELS:
            append_block(_table_text(item, doc), page, bbox, label, is_table=True)
            prev_was_list = False
            continue

        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue

        if label in _LIST_LABELS:
            if not prev_was_list:
                list_counter += 1
            append_block(text, page, bbox, label, list_group=f"L{list_counter}")
            prev_was_list = True
        else:
            append_block(text, page, bbox, label)
            prev_was_list = False

    page_count = len(getattr(doc, "pages", {}) or {}) or (
        max((b.page for b in blocks), default=1)
    )
    return ParsedDoc(page_count=page_count, blocks=blocks, full_text="".join(parts))
