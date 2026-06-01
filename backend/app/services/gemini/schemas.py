"""Structured-output JSON schema for every generation call.

This schema is the backbone of citation fidelity: the model must return per-claim cited
spans plus the carve-outs / answerability flags that the free gates check.
"""
from __future__ import annotations

ANSWER_SCHEMA: dict = {
    "type": "object",
    "required": ["answer", "claims", "answerable", "confidence"],
    "properties": {
        "answer": {"type": "string"},
        "answerable": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "missing_context": {"type": "array", "items": {"type": "string"}},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim_text", "chunk_id", "cited_span", "polarity"],
                "properties": {
                    "claim_text": {"type": "string"},
                    "chunk_id": {"type": "string"},
                    "cited_span": {"type": "string", "description": "verbatim source text"},
                    "page": {"type": "integer"},
                    "section": {"type": "string"},
                    "polarity": {"type": "string", "enum": ["affirmative", "negative"]},
                    "exceptions": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

# Cached, stable system prefix (grounding + abstention rules). Cache this, not the doc.
SYSTEM_PROMPT = (
    "You answer questions about a legal contract using ONLY the provided context. "
    "For every factual claim, cite the exact verbatim span and its chunk_id. "
    "If the context does not contain the answer, set answerable=false and list what is "
    "missing — never guess. Always surface carve-outs (except/unless/provided that/"
    "notwithstanding) in the relevant claim's exceptions[]. Reason before answering."
)
