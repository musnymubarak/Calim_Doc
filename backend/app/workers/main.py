"""arq worker: runs heavy ingestion off the request path.

Start with: arq app.workers.main.WorkerSettings
"""
from __future__ import annotations

import uuid

from arq.connections import RedisSettings

from app.config import settings
from app.db.session import SessionLocal
from app.services.ingestion.pipeline import ingest_document as run_ingest


async def ingest_document(ctx: dict, document_id: str) -> None:
    """Job enqueued by the upload endpoint. Name must match enqueue_job('ingest_document')."""
    async with SessionLocal() as db:
        await run_ingest(db, uuid.UUID(document_id))


class WorkerSettings:
    functions = [ingest_document]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
