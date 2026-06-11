"""Retry transient Gemini API failures with exponential backoff + jitter.

Retries server overloads (5xx, e.g. 503 UNAVAILABLE — "model experiencing high demand") and
rate limits (429 RESOURCE_EXHAUSTED), which are temporary. 4xx errors other than 429 are
deterministic (bad request, not found, permission) and re-raise immediately. Synchronous —
call sites already run inside asyncio.to_thread.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_ATTEMPTS = 6
_BASE_DELAY = 1.0   # seconds; grows 1s, 2s, 4s, 8s, 16s (+jitter, capped)
_MAX_DELAY = 20.0


def _is_transient(exc: Exception) -> bool:
    from google.genai.errors import ClientError, ServerError
    if isinstance(exc, ServerError):       # all 5xx, incl. 503 UNAVAILABLE
        return True
    if isinstance(exc, ClientError):        # only 429 is worth retrying
        return getattr(exc, "code", None) == 429
    return False


def with_retry(fn: Callable[[], T], *, what: str = "gemini call") -> T:
    """Run fn(), retrying transient Gemini errors with exponential backoff."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — re-raised below unless transient + retries left
            if attempt >= _MAX_ATTEMPTS or not _is_transient(exc):
                raise
            delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
            delay += random.uniform(0, delay * 0.25)  # jitter to avoid thundering herd
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                what, attempt, _MAX_ATTEMPTS, type(exc).__name__, delay,
            )
            time.sleep(delay)
    raise RuntimeError("unreachable")  # loop either returns or raises


def fallback_chain(primary: str) -> list[str]:
    """Build an ordered [primary, ...progressively weaker] model list.

    `call_with_model_fallback` only advances to the next entry when the current model stays
    *transiently* unavailable (sustained 503/429), so weaker models are reached ONLY as a
    last resort when the stronger ones are down — never preferred while the strong model works.
    """
    from app.config import settings

    # Strongest -> weakest capability ladder.
    ladder = [
        settings.gemini_model_accurate,   # Pro
        settings.gemini_model_fast,       # Flash
        settings.gemini_model_lite,       # Flash-Lite
    ]
    chain = [primary]
    if primary in ladder:
        chain += ladder[ladder.index(primary) + 1:]   # only models weaker than primary
    else:
        chain += ladder                                # custom primary: offer all tiers below
    if settings.gemini_model_fallback:
        chain.append(settings.gemini_model_fallback)   # honour any operator-configured fallback
    return list(dict.fromkeys(m for m in chain if m))  # dedupe, preserve order


def call_with_model_fallback(
    make_call: Callable[[str], T], models: list[str], *, what: str = "gemini call"
) -> T:
    """Try each model in order; within a model, with_retry handles transient blips. Move to the
    next model only when the current one stays transiently unavailable (e.g. a sustained 503
    'high demand' on the primary while a fallback model is healthy)."""
    ordered = list(dict.fromkeys(m for m in models if m))  # dedupe, preserve order
    last_exc: Exception | None = None
    for i, model in enumerate(ordered):
        try:
            return with_retry(lambda m=model: make_call(m), what=f"{what}[{model}]")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_transient(exc) or i == len(ordered) - 1:
                raise
            logger.warning("%s exhausted on %s — falling back to %s", what, model, ordered[i + 1])
    assert last_exc is not None
    raise last_exc
