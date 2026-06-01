"""Structure-extraction tests (pure regex, no external deps).

Run: `python backend/tests/test_structure.py` (backend on PYTHONPATH) or via pytest.
"""
from __future__ import annotations

from app.services.ingestion.chunk import ProvChunk
from app.services.ingestion.structure import extract_structures


def _chunk(ordinal: int, content: str, section_path: str) -> ProvChunk:
    return ProvChunk(
        ordinal=ordinal, content=content, page_start=1, page_end=1, bbox=[],
        section_path=section_path, char_start=0, char_end=len(content),
        is_table=False, list_group=None, token_count=max(1, len(content) // 4),
    )


def _doc() -> list[ProvChunk]:
    return [
        _chunk(0,
               'The "Disclosing Party" means the party that discloses Confidential '
               'Information to the receiving party (the "Recipient").',
               "1. Definitions"),
        _chunk(1,
               "This Agreement will automatically renew for successive one-year terms "
               "unless terminated.",
               "5. Term"),
        _chunk(2,
               "In the event of any conflict between this Agreement and a Schedule, this "
               "Agreement shall prevail, subject to Section 12.3. Notwithstanding anything "
               "to the contrary, the foregoing applies.",
               "8. Precedence"),
        _chunk(3, "Indemnification obligations are set out herein.", "12.3 Indemnification"),
    ]


def test_defined_terms():
    s = extract_structures(_doc())
    terms = {t["term"] for t in s.defined_terms}
    assert "Disclosing Party" in terms
    assert "Recipient" in terms
    dp = next(t for t in s.defined_terms if t["term"] == "Disclosing Party")
    assert "party that discloses" in dp["definition"]
    assert dp["source_chunk_ordinal"] == 0


def test_cross_ref_explicit_resolves():
    s = extract_structures(_doc())
    explicit = [e for e in s.cross_ref_edges if e["kind"] == "explicit"]
    sec = next(e for e in explicit if e["target_ref"] == "Section 12.3")
    assert sec["from_chunk_ordinal"] == 2
    assert sec["resolved"] is True
    assert sec["target_chunk_ordinal"] == 3      # heading "12.3 Indemnification"
    assert sec["confidence"] >= 0.9


def test_relative_ref_flagged_not_trusted():
    s = extract_structures(_doc())
    relative = [e for e in s.cross_ref_edges if e["kind"] == "relative"]
    assert relative, "expected relative refs to be flagged"
    assert all(e["resolved"] is False and e["confidence"] < 0.5 for e in relative)


def test_governance():
    s = extract_structures(_doc())
    kinds = {g["kind"] for g in s.governance_records}
    assert "renewal" in kinds       # "automatically renew"
    assert "precedence" in kinds     # "in the event of any conflict ... shall prevail"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all structure tests passed")
