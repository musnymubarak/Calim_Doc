"""Ingest-time correctness structures: defined terms, cross-ref graph, governance records.

Run once per document; power the always-on correctness defenses. Deterministic regex (no LLM
needed). The defined-term resolver is imperfect on real contracts — so cross-ref edges store
confidence and relative refs ("the foregoing", "notwithstanding...") are flagged, never trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.ingestion.chunk import ProvChunk

# ── Defined terms ────────────────────────────────────────────────────────────
_QUOTE = "[\"“”']"  # char class: straight/curly double quotes + straight single quote
_TERM = r'([A-Z][A-Za-z0-9 ,&/\-]{1,60}?)'

_QUOTED_MEANS = re.compile(
    rf'{_QUOTE}{_TERM}{_QUOTE}\s+'
    r'(?:means and includes|shall mean|means|refers to|has the meaning)\b'
    r'(.{0,300}?)(?:\.(?:\s|$)|;)',
    re.DOTALL,
)
_PARENS_DEF = re.compile(
    rf'\(\s*(?:the\s+|each\s+(?:an?\s+)?|an?\s+|collectively,?\s+|together,?\s+|'
    rf'individually,?\s+)?{_QUOTE}{_TERM}{_QUOTE}\s*\)'
)

# ── Cross references ─────────────────────────────────────────────────────────
_XREF = re.compile(
    r'\b(Sections?|Schedules?|Exhibits?|Articles?|Clauses?|Annex(?:es)?|Appendic(?:es|ix))\s+'
    r'([0-9]+(?:\.[0-9]+)*[A-Za-z]?)\b'
)
_INCORP = re.compile(r'incorporated\s+(?:herein\s+)?by\s+reference', re.IGNORECASE)
_RELATIVE = re.compile(
    r'\b(this (?:Section|Article|Agreement|Clause|Schedule)|the foregoing|'
    r'the preceding (?:Section|Article|paragraph)|notwithstanding anything to the contrary|'
    r'hereof|hereunder|herein|thereunder|thereof)\b',
    re.IGNORECASE,
)
_LEADING_NUMBER = re.compile(r'^\s*([0-9]+(?:\.[0-9]+)*[A-Za-z]?)\b')

# ── Governance clauses ───────────────────────────────────────────────────────
_GOVERNANCE: list[tuple[str, re.Pattern]] = [
    ("precedence", re.compile(
        r'order of precedence|shall (?:prevail|control|govern|take precedence)|'
        r'(?:in the event|to the extent) of (?:any )?(?:conflict|inconsistency)',
        re.IGNORECASE)),
    ("MFN", re.compile(r'most[\s\-]favou?red(?:[\s\-]nation)?|\bMFN\b', re.IGNORECASE)),
    ("renewal", re.compile(
        r'automatically renew|auto[\s\-]renew|renewal term|evergreen', re.IGNORECASE)),
    ("conflict", re.compile(r'conflict between|inconsistency between', re.IGNORECASE)),
]

_KIND_NORMAL = {
    "section": "Section", "schedule": "Schedule", "exhibit": "Exhibit", "article": "Article",
    "clause": "Clause", "annex": "Annex", "appendix": "Appendix", "appendices": "Appendix",
}


@dataclass
class Structures:
    defined_terms: list[dict] = field(default_factory=list)      # {term, definition, source_chunk_ordinal, depth}
    cross_ref_edges: list[dict] = field(default_factory=list)    # {from_chunk_ordinal, target_ref, target_chunk_ordinal, kind, confidence, resolved}
    governance_records: list[dict] = field(default_factory=list) # {kind, chunk_ordinal, detail}


def _extract_defined_terms(chunks: list[ProvChunk]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in chunks:
        for m in _QUOTED_MEANS.finditer(c.content):
            term = m.group(1).strip()
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "term": term,
                "definition": re.sub(r"\s+", " ", m.group(2)).strip(),
                "source_chunk_ordinal": c.ordinal,
                "depth": 0,  # TODO: resolve nested defined-term references with a depth cap
            })
        for m in _PARENS_DEF.finditer(c.content):
            term = m.group(1).strip()
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            start = max(0, m.start() - 200)
            out.append({
                "term": term,
                "definition": re.sub(r"\s+", " ", c.content[start:m.start()]).strip(),
                "source_chunk_ordinal": c.ordinal,
                "depth": 0,
            })
    return out


def _number_index(chunks: list[ProvChunk]) -> dict[str, int]:
    """Map a section number (e.g. '12.3') -> first chunk ordinal whose heading starts with it."""
    index: dict[str, int] = {}
    for c in chunks:
        heading = (c.section_path or "").split(" > ")[-1] if c.section_path else ""
        for candidate in (heading, c.content[:40]):
            m = _LEADING_NUMBER.match(candidate)
            if m:
                index.setdefault(m.group(1), c.ordinal)
                break
    return index


def _extract_cross_refs(chunks: list[ProvChunk]) -> list[dict]:
    number_index = _number_index(chunks)
    seen: set[tuple[int, str]] = set()
    out: list[dict] = []

    def add(from_ord: int, target_ref: str, kind: str, confidence: float,
            target_ord: int | None) -> None:
        key = (from_ord, target_ref.lower())
        if key in seen:
            return
        seen.add(key)
        out.append({
            "from_chunk_ordinal": from_ord,
            "target_ref": target_ref,
            "target_chunk_ordinal": target_ord,
            "kind": kind,
            "confidence": confidence,
            "resolved": target_ord is not None,
        })

    for c in chunks:
        for m in _XREF.finditer(c.content):
            kind_word = _KIND_NORMAL.get(m.group(1).rstrip("s").lower(), m.group(1))
            number = m.group(2)
            target_ref = f"{kind_word} {number}"
            target_ord = number_index.get(number)
            add(c.ordinal, target_ref, "explicit", 0.9 if target_ord is not None else 0.6, target_ord)
        if _INCORP.search(c.content):
            add(c.ordinal, "incorporated by reference", "incorporation", 0.3, None)
        for m in _RELATIVE.finditer(c.content):
            add(c.ordinal, m.group(1).strip(), "relative", 0.2, None)
    return out


def _extract_governance(chunks: list[ProvChunk]) -> list[dict]:
    out: list[dict] = []
    for c in chunks:
        for kind, pattern in _GOVERNANCE:
            m = pattern.search(c.content)
            if m:
                start = max(0, m.start() - 40)
                end = min(len(c.content), m.end() + 40)
                out.append({
                    "kind": kind,
                    "chunk_ordinal": c.ordinal,
                    "detail": re.sub(r"\s+", " ", c.content[start:end]).strip(),
                })
    return out


def extract_structures(chunks: list[ProvChunk]) -> Structures:
    return Structures(
        defined_terms=_extract_defined_terms(chunks),
        cross_ref_edges=_extract_cross_refs(chunks),
        governance_records=_extract_governance(chunks),
    )
