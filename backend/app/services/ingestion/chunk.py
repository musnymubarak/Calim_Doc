"""Provenance-preserving chunker.

Rules (the spine of citation fidelity):
  - ~500-800 tokens/chunk, ~15% overlap, structure-aware splits.
  - Tables = ONE atomic chunk, alone (never merged with surrounding prose).
  - NEVER split a list group ((a)-(z) / (i)-(x)) across chunks.
  - Carry page/bbox/section_path/char offsets on every chunk — never dropped.

Approach: group blocks into indivisible *units* (a single block, a whole consecutive list
group, or a table), then greedily pack units into chunks up to a token budget. A chunk's
`content` is the exact slice of `full_text` spanning its units, so any verbatim span the
model cites from the provided context will substring-match the chunk (the citation gate).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.ingestion.parse import ParsedBlock, ParsedDoc


@dataclass
class ProvChunk:
    ordinal: int
    content: str
    page_start: int
    page_end: int
    bbox: list[dict]
    section_path: str
    char_start: int
    char_end: int
    is_table: bool
    list_group: str | None
    token_count: int


@dataclass
class _Unit:
    blocks: list[ParsedBlock]
    is_table: bool
    token_count: int


def estimate_tokens(text: str) -> int:
    """Cheap ~4-chars/token estimate. Swap for a real tokenizer (Gemini count_tokens or a
    HF tokenizer) when you want exact budgets — call sites only depend on this function."""
    return max(1, len(text) // 4)


def _build_units(blocks: list[ParsedBlock]) -> list[_Unit]:
    """Collapse blocks into indivisible units: tables alone, list groups together."""
    units: list[_Unit] = []
    i = 0
    n = len(blocks)
    while i < n:
        b = blocks[i]
        if b.is_table:
            units.append(_Unit([b], is_table=True, token_count=estimate_tokens(b.text)))
            i += 1
        elif b.list_group is not None:
            group = [b]
            j = i + 1
            while j < n and blocks[j].list_group == b.list_group:
                group.append(blocks[j])
                j += 1
            tokens = sum(estimate_tokens(x.text) for x in group)
            units.append(_Unit(group, is_table=False, token_count=tokens))
            i = j
        else:
            units.append(_Unit([b], is_table=False, token_count=estimate_tokens(b.text)))
            i += 1
    return units


def _make_chunk(ordinal: int, units: list[_Unit], full_text: str) -> ProvChunk:
    blocks = [b for u in units for b in u.blocks]
    char_start = min(b.char_start for b in blocks)
    char_end = max(b.char_end for b in blocks)
    bbox = [bb for b in blocks for bb in b.bbox]
    return ProvChunk(
        ordinal=ordinal,
        content=full_text[char_start:char_end],   # exact source slice → citation-matchable
        page_start=min(b.page for b in blocks),
        page_end=max(b.page for b in blocks),
        bbox=bbox,
        section_path=blocks[0].section_path,
        char_start=char_start,
        char_end=char_end,
        is_table=any(u.is_table for u in units),
        list_group=blocks[0].list_group,
        token_count=sum(u.token_count for u in units),
    )


def chunk_document(
    parsed: ParsedDoc, *, target_tokens: int = 650, overlap: float = 0.15
) -> list[ProvChunk]:
    units = _build_units(parsed.blocks)
    overlap_budget = int(target_tokens * overlap)

    chunks: list[ProvChunk] = []
    current: list[_Unit] = []
    current_tokens = 0
    has_new_content = False     # guard against emitting an overlap-only tail chunk

    def emit() -> list[_Unit]:
        """Emit the current chunk; return trailing units to seed the next (for overlap)."""
        if not (current and has_new_content):
            return []
        chunks.append(_make_chunk(len(chunks), current, parsed.full_text))
        # Seed overlap with the last non-table unit if it fits the overlap budget.
        last = current[-1]
        if not last.is_table and last.token_count <= overlap_budget:
            return [last]
        return []

    for unit in units:
        if unit.is_table:
            emit()
            chunks.append(_make_chunk(len(chunks), [unit], parsed.full_text))
            current, current_tokens, has_new_content = [], 0, False
            continue

        if current and current_tokens + unit.token_count > target_tokens:
            seed = emit()
            current = list(seed)
            current_tokens = sum(u.token_count for u in seed)
            has_new_content = False

        current.append(unit)
        current_tokens += unit.token_count
        has_new_content = True

    if current and has_new_content:
        chunks.append(_make_chunk(len(chunks), current, parsed.full_text))

    return chunks
