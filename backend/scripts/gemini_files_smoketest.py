"""Standalone smoke test for the Gemini File API engine (no Postgres/FastAPI needed).

Mirrors app/services/gemini_files — upload a document, then ask a grounded question with
structured citations. Validates the engine with just an API key.

Setup:
    pip install google-genai
    set GEMINI_API_KEY=...        (PowerShell: $env:GEMINI_API_KEY="...")
Run:
    python backend/scripts/gemini_files_smoketest.py [path_to_document]
"""
from __future__ import annotations

import json
import os
import sys
import time

DEFAULT_DOC = r"C:\Users\musny\Desktop\Hashnate\Calim_Document_Analyzis\data\sample_contract.txt"
MODEL = os.environ.get("GEMINI_MODEL_FAST", "gemini-flash-latest")

SCHEMA = {
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
                "required": ["claim_text", "cited_quote"],
                "properties": {
                    "claim_text": {"type": "string"},
                    "cited_quote": {"type": "string"},
                    "page": {"type": "integer"},
                    "section": {"type": "string"},
                    "exceptions": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

SYSTEM_PROMPT = (
    "You answer questions about the attached legal contract using ONLY its contents. For every "
    "claim include the exact verbatim quote and page. If the contract lacks the answer, set "
    "answerable=false and say what's missing. Surface carve-outs in exceptions[]."
)


def main() -> None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("Set GEMINI_API_KEY first."); return
    doc = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOC

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)

    print(f"uploading: {doc}")
    f = client.files.upload(file=doc)
    while getattr(getattr(f, "state", None), "name", "") not in ("ACTIVE", ""):
        if getattr(getattr(f, "state", None), "name", "") == "FAILED":
            print("upload FAILED"); return
        time.sleep(2)
        f = client.files.get(name=f.name)
    print(f"uploaded: {f.name}")

    question = "What is the limitation of liability cap, and what are the exceptions to it?"
    resp = client.models.generate_content(
        model=MODEL,
        contents=[f, f"QUESTION: {question}"],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=SCHEMA,
            max_output_tokens=1500,
        ),
    )
    print("\n=== answer ===")
    try:
        print(json.dumps(json.loads(resp.text), indent=2))
    except Exception:
        print(resp.text)

    usage = getattr(resp, "usage_metadata", None)
    if usage:
        print(f"\ntokens: in={getattr(usage, 'prompt_token_count', '?')} "
              f"out={getattr(usage, 'candidates_token_count', '?')}")


if __name__ == "__main__":
    main()
