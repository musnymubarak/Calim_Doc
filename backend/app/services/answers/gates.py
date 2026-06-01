"""Free, deterministic correctness gates that run on every answer.

Carve-out sufficiency: if a cited clause carries a carve-out (except/unless/provided that/
notwithstanding/save for/subject to) in the SAME clause as the obligation, but the model's
`exceptions[]` is empty, the answer is probably missing a limitation → escalate. Boilerplate
"subject to the terms of this Agreement" is ignored (it's not a substantive carve-out).
"""
from __future__ import annotations

_CARVE_MARKERS = ("except", "unless", "provided that", "provided, however",
                  "notwithstanding", "save for", "subject to")
_BOILERPLATE = ("subject to the terms", "subject to the provisions",
                "subject to the foregoing")

# High-stakes clause types → escalate up front (cost of wrong >> the ~$0.02 delta).
HIGH_STAKES = {
    "indemnity", "indemnification", "limitation of liability", "liability",
    "termination", "ip assignment", "intellectual property", "change of control",
    "governing law", "auto-renewal", "renewal",
}

SCORE_GAP_FLOOR = 0.01     # flat RRF distribution → weak retrieval (tune empirically)


def carve_out_unaddressed(claims: list[dict]) -> bool:
    """True if any cited claim has a substantive carve-out but an empty exceptions[]."""
    for claim in claims:
        span = (claim.get("cited_span") or "").lower()
        if not span:
            continue
        for b in _BOILERPLATE:
            span = span.replace(b, "")
        has_carve = any(marker in span for marker in _CARVE_MARKERS)
        if has_carve and not claim.get("exceptions"):
            return True
    return False


def should_escalate(*, all_verified: bool, coverage: float, score_gap: float,
                    guards: list[str], answerable: bool, question: str,
                    sparse: bool = False) -> str | None:
    """Return an escalation reason if any cheap trigger fires, else None.

    NEVER gate on self-reported confidence or embedding-cosine grounding — only structural signals.
    """
    if not all_verified:
        return "citation_gate_failed"
    if coverage < 1.0:
        return "incomplete_citation_coverage"
    if not answerable:
        return "not_answerable_on_cheap_path"
    # `sparse` (fewer than 5 fused candidates) is thin coverage even with a wide score gap.
    if sparse or score_gap < SCORE_GAP_FLOOR:
        return "weak_retrieval"
    if guards:
        return f"guard_activated:{','.join(sorted(set(guards)))}"
    if any(term in question.lower() for term in HIGH_STAKES):
        return "high_stakes_clause"
    return None
