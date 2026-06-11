"""Lightweight PDF text extraction → ParsedDoc, with NO Docling/OCR dependency.

Used by the RAG fallback for documents too large for whole-file Gemini attachment. It relies
on the PDF already carrying a text layer (true for digital PDFs and for scanned-then-OCR'd
contracts). Pages with no extractable text are skipped — a purely scanned PDF with no OCR
layer yields no blocks, which the caller surfaces as a clear ingestion failure.

Output shape matches Docling's parse_document() so the existing chunk_document() /
extract_structures() / embed / persist pipeline consumes it unchanged. Blocks carry real page
numbers and exact char offsets into full_text (the citation-fidelity contract); bbox and
section_path are empty because a text-only extractor has no layout geometry.
"""
from __future__ import annotations

import re

from app.services.ingestion.parse import ParsedBlock, ParsedDoc

# Hard-wrap any single paragraph longer than this many chars so no block (and therefore no
# embed input) is unwieldy. ~2000 chars ≈ 500 tokens, well under the embedding input limit.
_MAX_BLOCK_CHARS = 2000

_PARA_SPLIT = re.compile(r"\n\s*\n")


def _segments(page_text: str) -> list[str]:
    """Split a page's text into paragraph-sized segments, hard-wrapping oversized ones."""
    out: list[str] = []
    for para in _PARA_SPLIT.split(page_text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= _MAX_BLOCK_CHARS:
            out.append(para)
            continue
        for i in range(0, len(para), _MAX_BLOCK_CHARS):
            piece = para[i : i + _MAX_BLOCK_CHARS].strip()
            if piece:
                out.append(piece)
    return out


def parse_pdf_text(file_path: str) -> ParsedDoc:
    """Extract per-page text with pypdf and build a ParsedDoc the chunker can consume.

    full_text is the "\n\n"-joined concatenation of every segment in reading order; each
    block's [char_start, char_end) slices back to exactly that block's text, so any verbatim
    span the model later cites substring-matches its chunk (the citation gate).
    """
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    blocks: list[ParsedBlock] = []
    parts: list[str] = []
    cursor = 0
    sep = "\n\n"

    for page_no, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — a single corrupt page shouldn't kill ingestion
            page_text = ""
        for seg in _segments(page_text):
            start = cursor
            end = start + len(seg)
            blocks.append(ParsedBlock(
                text=seg,
                page=page_no,
                bbox=[],
                section_path="",
                label="text",
                char_start=start,
                char_end=end,
            ))
            parts.append(seg)
            cursor = end + len(sep)  # account for the join separator

    return ParsedDoc(page_count=len(reader.pages), blocks=blocks, full_text=sep.join(parts))
