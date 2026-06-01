"""Citation-verification gate — the fidelity spine.

Substring presence proves the quote is REAL (not that it supports the claim — that's the
critic pass). A cited span must offset-match its chunk's content. Returns per-claim verified
flags + an overall coverage signal used by the escalation router.
"""
from __future__ import annotations

import re


def _normalize(text: str) -> str:
    """Collapse whitespace so PDF line-wrapping doesn't break exact matching."""
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_claim(cited_span: str, chunk_content: str) -> bool:
    """True if the cited span actually appears in the chunk (whitespace-normalized)."""
    if not cited_span:
        return False
    return _normalize(cited_span) in _normalize(chunk_content)


def verify_answer(claims: list[dict], chunks_by_id: dict[str, str]) -> dict:
    """Verify every claim's cited span against the chunk it points at.

    Returns: {verified_claims, all_verified, coverage} — coverage feeds escalation.
    """
    verified = []
    for claim in claims:
        chunk = chunks_by_id.get(str(claim.get("chunk_id")), "")
        ok = verify_claim(claim.get("cited_span", ""), chunk)
        verified.append({**claim, "verified": ok})

    total = len(verified) or 1
    n_ok = sum(1 for c in verified if c["verified"])
    return {
        "verified_claims": verified,
        "all_verified": n_ok == len(verified) and len(verified) > 0,
        "coverage": n_ok / total,
    }
