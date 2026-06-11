"""Gemini client wrapper: model registry, embeddings, structured generation, caching.

Thin layer over google-genai. Model IDs come from settings (registry), never hardcoded.
Generation calls force structured output via ANSWER_SCHEMA and cache the stable system
prefix. Bodies are stubs to be implemented against the live SDK.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field

from app.config import settings

_EMBED_BATCH = 100  # contents per embed request


def _normalize(vec: list[float]) -> list[float]:
    """Unit-normalize. Recommended for gemini-embedding-001 when truncating below 3072 dims."""
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec

# Tier -> model registry (operator-configurable via env).
MODEL_REGISTRY: dict[str, str] = {
    "fast": settings.gemini_model_fast,        # baseline (Flash)
    "balanced": settings.gemini_model_fast,    # Flash + thinking
    "accurate": settings.gemini_model_accurate,  # Pro (escalation)
}


@dataclass
class GenResult:
    data: dict                                  # parsed structured output (ANSWER_SCHEMA)
    model: str
    token_usage: dict = field(default_factory=dict)  # {input, output, cached}


class GeminiClient:
    def __init__(self) -> None:
        # from google import genai
        # self._client = genai.Client(api_key=settings.gemini_api_key)
        self._client = None  # TODO: init google-genai client

    async def embed(
        self, texts: list[str], *, batch: bool = False, task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> list[list[float]]:
        """Embed texts with gemini-embedding-001, truncated to EMBEDDING_DIM (MRL) + normalized.

        Runs the sync SDK off the event loop. `batch=True` should route to the Batch API
        (flat 50% off) for ingestion — TODO; currently uses the sync path either way.
        """
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts, task_type)

    def _embed_sync(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google import genai
        from google.genai import types

        if self._client is None:
            self._client = genai.Client(api_key=settings.gemini_api_key)

        from app.services.gemini.retry import with_retry

        vectors: list[list[float]] = []
        for i in range(0, len(texts), _EMBED_BATCH):
            chunk = texts[i:i + _EMBED_BATCH]
            resp = with_retry(lambda: self._client.models.embed_content(
                model=settings.gemini_embedding_model,
                contents=chunk,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=settings.embedding_dim,
                ),
            ), what="embed_content")
            vectors.extend(_normalize(list(e.values)) for e in resp.embeddings)
        return vectors

    async def generate(
        self,
        *,
        tier: str,
        system_prompt: str,
        context: str,
        question: str,
        thinking_budget: int = 0,
        max_output_tokens: int | None = None,
    ) -> GenResult:
        """Structured generation. Forces ANSWER_SCHEMA; runs the sync SDK off the event loop."""
        model = MODEL_REGISTRY.get(tier, settings.gemini_model_fast)
        return await asyncio.to_thread(
            self._generate_sync, model, system_prompt, context, question,
            thinking_budget, max_output_tokens or settings.max_output_tokens,
        )

    def _generate_sync(
        self, model: str, system_prompt: str, context: str, question: str,
        thinking_budget: int, max_output_tokens: int,
    ) -> GenResult:
        from app.services.gemini.schemas import ANSWER_SCHEMA

        prompt = f"CONTEXT:\n{context}\n\nQUESTION: {question}"
        fallback = {"answer": "", "claims": [], "answerable": False, "confidence": "low"}
        return self._generate_json_sync(
            model, system_prompt, prompt, ANSWER_SCHEMA, thinking_budget,
            max_output_tokens, fallback,
        )

    async def generate_json(
        self, *, model: str, system_prompt: str, prompt: str, schema: dict,
        max_output_tokens: int, thinking_budget: int = 0,
    ) -> GenResult:
        """Structured generation against an arbitrary schema + plain prompt (no document
        attached). Used by the RAG risk-report path, which feeds retrieved context as text."""
        return await asyncio.to_thread(
            self._generate_json_sync, model, system_prompt, prompt, schema,
            thinking_budget, max_output_tokens, {},
        )

    def _generate_json_sync(
        self, model: str, system_prompt: str, prompt: str, schema: dict,
        thinking_budget: int, max_output_tokens: int, fallback: dict,
    ) -> GenResult:
        import copy
        import json

        from google import genai
        from google.genai import types

        if self._client is None:
            self._client = genai.Client(api_key=settings.gemini_api_key)

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            # Deep-copy: the SDK mutates the schema dict in place, corrupting module constants.
            response_schema=copy.deepcopy(schema),
            max_output_tokens=max_output_tokens,
            # thinking bills as output — keep it off on the cheap path, raise on escalation.
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
        )
        from app.services.gemini.retry import call_with_model_fallback, fallback_chain
        resp = call_with_model_fallback(
            lambda m: self._client.models.generate_content(model=m, contents=prompt, config=config),
            fallback_chain(model),
            what="generate_content",
        )

        try:
            data = json.loads(resp.text)
        except (json.JSONDecodeError, TypeError):
            data = dict(fallback) if fallback else {}
            if fallback:
                data["answer"] = resp.text or ""

        usage = getattr(resp, "usage_metadata", None)
        token_usage = {
            "input": getattr(usage, "prompt_token_count", 0) or 0,
            "output": getattr(usage, "candidates_token_count", 0) or 0,
            "cached": getattr(usage, "cached_content_token_count", 0) or 0,
        }
        return GenResult(data=data, model=model, token_usage=token_usage)


_client: GeminiClient | None = None


def get_gemini() -> GeminiClient:
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
