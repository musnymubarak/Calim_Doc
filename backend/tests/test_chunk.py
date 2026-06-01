"""Chunker invariants (no Docling needed — operates on ParsedBlock/ParsedDoc).

Run directly: `python backend/tests/test_chunk.py` (with backend on PYTHONPATH), or via pytest.
"""
from __future__ import annotations

from app.services.ingestion.chunk import chunk_document
from app.services.ingestion.parse import ParsedBlock, ParsedDoc


def _build(specs: list[dict]) -> ParsedDoc:
    """Build a ParsedDoc the same way parse.py does, so char offsets are consistent."""
    blocks: list[ParsedBlock] = []
    parts: list[str] = []
    cursor = 0
    for s in specs:
        text = s["text"]
        start = cursor
        parts.append(text)
        cursor += len(text)
        end = cursor
        parts.append("\n\n")
        cursor += 2
        blocks.append(ParsedBlock(
            text=text, page=s.get("page", 1), bbox=[], section_path=s.get("sp", ""),
            label=s.get("label", "text"), char_start=start, char_end=end,
            is_table=s.get("is_table", False), list_group=s.get("lg"),
        ))
    return ParsedDoc(page_count=1, blocks=blocks, full_text="".join(parts))


def _doc() -> ParsedDoc:
    long = "word " * 30  # ~150 chars ≈ 37 tokens, forces splits at target=20
    return _build([
        {"text": "Section 1 Definitions", "label": "section_header", "sp": "Section 1 Definitions"},
        {"text": "Prose A. " + long, "sp": "Section 1 Definitions", "page": 1},
        {"text": "item one alpha", "label": "list_item", "lg": "L1", "page": 1},
        {"text": "item two beta", "label": "list_item", "lg": "L1", "page": 1},
        {"text": "item three gamma", "label": "list_item", "lg": "L1", "page": 2},
        {"text": "TABLE caption | a | b | 1 | 2", "label": "table", "is_table": True, "page": 2},
        {"text": "Prose B. " + long, "sp": "Section 1 Definitions", "page": 3},
    ])


def test_content_is_exact_source_slice():
    doc = _doc()
    chunks = chunk_document(doc, target_tokens=20, overlap=0.15)
    assert chunks, "expected at least one chunk"
    for c in chunks:
        assert c.content == doc.full_text[c.char_start:c.char_end]


def test_table_is_atomic_and_alone():
    doc = _doc()
    chunks = chunk_document(doc, target_tokens=20, overlap=0.15)
    table_chunks = [c for c in chunks if c.is_table]
    assert len(table_chunks) == 1
    assert table_chunks[0].content.strip() == "TABLE caption | a | b | 1 | 2"
    # The table text must not bleed into any non-table chunk.
    for c in chunks:
        if not c.is_table:
            assert "TABLE caption" not in c.content


def test_list_group_never_split():
    doc = _doc()
    chunks = chunk_document(doc, target_tokens=20, overlap=0.15)
    holding = [i for i, c in enumerate(chunks)
               if any(k in c.content for k in ("item one", "item two", "item three"))]
    assert len(set(holding)) == 1, "list group L1 was split across chunks"
    c = chunks[holding[0]]
    assert all(k in c.content for k in ("item one", "item two", "item three"))
    assert c.page_start == 1 and c.page_end == 2  # spans pages within the group


def test_ordinals_sequential():
    doc = _doc()
    chunks = chunk_document(doc, target_tokens=20, overlap=0.15)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all chunker tests passed")
