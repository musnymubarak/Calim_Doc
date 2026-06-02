"""arq worker: runs heavy ingestion off the request path.

Start with: arq app.workers.main.WorkerSettings
"""
from __future__ import annotations

import uuid

from arq.connections import RedisSettings

from app.config import settings
from app.db.session import SessionLocal
from app.services.gemini_files.engine import ingest_to_gemini


async def ingest_document(ctx: dict, document_id: str) -> None:
    """Job enqueued by the upload endpoint. Name must match enqueue_job('ingest_document').

    Gemini File API engine: uploads the document to the Files API.
    (Legacy RAG ingestion → app.services.ingestion.pipeline; NotebookLM spike →
    app.services.notebooklm.engine — both retained but unused.)
    """
    async with SessionLocal() as db:
        await ingest_to_gemini(db, uuid.UUID(document_id))


class WorkerSettings:
    functions = [ingest_document]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
