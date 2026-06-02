"""Gemini File API client: upload a document, then ask grounded questions against it.

Official google-genai SDK — no browser automation. Files API stores uploads ~48h (we track
expiry and re-upload on demand). Generation uses structured output to force per-claim cited
quotes + page numbers. Sync SDK calls are run off the event loop.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

from app.config import settings


@dataclass
class UploadedFile:
    name: str               # "files/abc123"
    uri: str | None
    expires_at: object | None   # tz-aware datetime from the SDK, or None


@dataclass
class GenResult:
    data: dict
    model: str
    token_usage: dict = field(default_factory=dict)


class GeminiFilesClient:
    def __init__(self) -> None:
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    # ── upload ────────────────────────────────────────────────────────────
    async def upload(self, file_path: str, mime_type: str | None = None) -> UploadedFile:
        return await asyncio.to_thread(self._upload_sync, file_path, mime_type)

    def _upload_sync(self, file_path: str, mime_type: str | None) -> UploadedFile:
        client = self._ensure_client()
        try:
            f = client.files.upload(file=file_path)
        except TypeError:  # older SDK arg name
            f = client.files.upload(path=file_path)

        # Wait until the file finishes processing (PDFs are parsed server-side).
        for _ in range(150):  # ~5 min cap
            state = getattr(getattr(f, "state", None), "name", str(getattr(f, "state", "")))
            if state in ("ACTIVE", ""):
                break
            if state == "FAILED":
                raise RuntimeError(f"Gemini file processing failed: {getattr(f, 'name', '?')}")
            time.sleep(2)
            f = client.files.get(name=f.name)

        return UploadedFile(
            name=f.name,
            uri=getattr(f, "uri", None),
            expires_at=getattr(f, "expiration_time", None),
        )

    # ── grounded answer ───────────────────────────────────────────────────
    async def answer(self, file_name: str, question: str, *, model: str,
                     system_prompt: str, schema: dict, max_output_tokens: int) -> GenResult:
        return await asyncio.to_thread(
            self._answer_sync, file_name, question, model, system_prompt, schema, max_output_tokens
        )

    def _answer_sync(self, file_name: str, question: str, model: str, system_prompt: str,
                     schema: dict, max_output_tokens: int) -> GenResult:
        from google.genai import types

        client = self._ensure_client()
        file_obj = client.files.get(name=file_name)   # reconstruct the File handle

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=max_output_tokens,
        )
        resp = client.models.generate_content(
            model=model, contents=[file_obj, f"QUESTION: {question}"], config=config
        )

        try:
            data = json.loads(resp.text)
        except (json.JSONDecodeError, TypeError):
            data = {"answer": resp.text or "", "claims": [], "answerable": False,
                    "confidence": "low"}

        usage = getattr(resp, "usage_metadata", None)
        token_usage = {
            "input": getattr(usage, "prompt_token_count", 0) or 0,
            "output": getattr(usage, "candidates_token_count", 0) or 0,
            "cached": getattr(usage, "cached_content_token_count", 0) or 0,
        }
        return GenResult(data=data, model=model, token_usage=token_usage)


_client: GeminiFilesClient | None = None


def get_gemini_files() -> GeminiFilesClient:
    global _client
    if _client is None:
        _client = GeminiFilesClient()
    return _client
