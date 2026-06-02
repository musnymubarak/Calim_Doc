"""NotebookLM engine: replaces the RAG pipeline. Ingestion = upload the contract as a source
into a per-document notebook; answering = ask the notebook and pass through its grounded
citations.

NotebookLM does its own chunking/retrieval/grounding, so there is no chunk store, no embedding,
no escalation ladder, and no local citation-verification gate (we can't verify against chunks
we don't have). That control is traded away deliberately — the point of this branch.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services.notebooklm.client import get_notebooklm

logger = logging.getLogger(__name__)


@dataclass
class AnswerResult:
    answer: str
    citations: list = field(default_factory=list)
    exceptions: list = field(default_factory=list)
    answerable: bool | None = None
    missing_context: list = field(default_factory=list)
    confidence: str | None = None
    model: str | None = "notebooklm"
    tier: str | None = "notebooklm"
    escalated: bool = False
    escalation_reason: str | None = None
    token_usage: dict = field(default_factory=dict)


def _normalize_citations(raw: list) -> list[dict]:
    """Normalize NotebookLM citations to {marker, quote} (+passthrough).

    roomi-fields returns {marker, number, sourceText}; other servers vary, so we fall back
    across common key names.
    """
    out: list[dict] = []
    for c in raw or []:
        if isinstance(c, dict):
            out.append({
                "marker": c.get("marker") or c.get("number"),
                "quote": c.get("sourceText") or c.get("quote") or c.get("text") or c.get("snippet"),
                "source": c.get("source") or c.get("title"),
                "raw": c,
            })
        else:
            out.append({"quote": str(c)})
    return out


async def ingest_to_notebooklm(db: AsyncSession, document_id: uuid.UUID) -> None:
    """Upload the document to NotebookLM as a source within a per-document notebook."""
    doc = await db.get(Document, document_id)
    if doc is None:
        return

    async def set_status(status: str) -> None:
        doc.status = status
        await db.commit()

    try:
        await set_status("processing")
        client = get_notebooklm()
        notebook_url = doc.notebooklm_notebook_id or await client.create_notebook(
            f"contract-{doc.id}"
        )
        # The server reads this path from ITS OWN filesystem → the NotebookLM service must share
        # the files volume with the backend at the same path (/data/files). No bytes are uploaded.
        source_id = await client.add_source(notebook_url, doc.storage_uri)

        doc.notebooklm_notebook_id = notebook_url   # column holds the notebook_url handle
        doc.notebooklm_source_id = source_id
        await set_status("ready")
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        await db.rollback()
        doc.status = "failed"
        doc.error_msg = str(exc)
        await db.commit()
        raise


async def answer_question(
    db: AsyncSession,
    document_id: uuid.UUID,
    question: str,
    tier_override: str | None = None,   # accepted for API compatibility; NotebookLM has no tiers
) -> AnswerResult:
    doc = await db.get(Document, document_id)
    if doc is None or not doc.notebooklm_notebook_id:
        return AnswerResult(
            answer="This document is not ready yet (still ingesting into NotebookLM).",
            answerable=False, confidence="low",
        )

    res = await get_notebooklm().ask(doc.notebooklm_notebook_id, question)
    answer = res.get("answer", "") or ""
    return AnswerResult(
        answer=answer,
        citations=_normalize_citations(res.get("citations", [])),
        answerable=bool(answer.strip()),
    )
