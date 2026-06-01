"""Escalation-trigger and carve-out gate tests (pure logic — no DB/SDK).

Run: `python backend/tests/test_answers.py` (backend on PYTHONPATH) or via pytest.
"""
from __future__ import annotations

from app.services.answers.gates import carve_out_unaddressed, should_escalate

_GOOD = dict(all_verified=True, coverage=1.0, score_gap=0.5, guards=[],
             answerable=True, question="what is the notice address")


def test_no_escalation_on_clean_answer():
    assert should_escalate(**_GOOD) is None


def test_escalates_on_failed_citation():
    assert should_escalate(**{**_GOOD, "all_verified": False}) == "citation_gate_failed"


def test_escalates_on_low_coverage():
    assert should_escalate(**{**_GOOD, "coverage": 0.5}) == "incomplete_citation_coverage"


def test_escalates_on_not_answerable():
    assert should_escalate(**{**_GOOD, "answerable": False}) == "not_answerable_on_cheap_path"


def test_escalates_on_weak_retrieval():
    assert should_escalate(**{**_GOOD, "score_gap": 0.0}) == "weak_retrieval"


def test_escalates_on_sparse_even_with_wide_gap():
    # Fewer than 5 fused candidates is thin coverage even if the score gap looks wide.
    assert should_escalate(**{**_GOOD, "sparse": True}) == "weak_retrieval"


def test_escalates_on_guard():
    r = should_escalate(**{**_GOOD, "guards": ["cross_ref", "precedence"]})
    assert r is not None and r.startswith("guard_activated:")


def test_escalates_on_high_stakes_question():
    r = should_escalate(**{**_GOOD, "question": "what is the limitation of liability cap?"})
    assert r == "high_stakes_clause"


def test_confidence_never_drives_escalation():
    # A clean structural answer must NOT escalate even if we'd informally call it low-confidence.
    assert should_escalate(**_GOOD) is None


def test_carve_out_unaddressed_flags_missing_exception():
    claims = [{"cited_span": "The Provider shall be liable, except for indirect damages.",
               "exceptions": []}]
    assert carve_out_unaddressed(claims) is True


def test_carve_out_ok_when_exception_captured():
    claims = [{"cited_span": "The Provider shall be liable, except for indirect damages.",
               "exceptions": ["indirect damages"]}]
    assert carve_out_unaddressed(claims) is False


def test_carve_out_ignores_boilerplate():
    claims = [{"cited_span": "Subject to the terms of this Agreement, fees are due in 30 days.",
               "exceptions": []}]
    assert carve_out_unaddressed(claims) is False


def test_carve_out_none_when_no_marker():
    claims = [{"cited_span": "The fee is $1,000 per month.", "exceptions": []}]
    assert carve_out_unaddressed(claims) is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all answer-gate tests passed")
