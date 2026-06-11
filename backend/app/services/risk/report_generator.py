"""Service to generate Risk Reports using the Gemini Files API."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document
from app.models.report import RiskReport
from app.services.gemini_files.client import get_gemini_files
from app.services.gemini_files.engine import _ensure_uploaded
from app.services.risk.schemas import RISK_REPORT_SCHEMA, RISK_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

async def generate_report(
    db: AsyncSession, 
    document_id: uuid.UUID, 
    model: str | None = None
) -> RiskReport | None:
    """Generates a RiskReport for the given document and saves it."""
    doc = await db.get(Document, document_id)
    if not doc:
        return None

    # Default to the flash model if none provided
    use_model = model or settings.gemini_model_fast

    question = "Analyze this contract for risks. Look for liabilities, termination pitfalls, IP terms, payment schedules, and any other critical issues."

    from sqlalchemy import select
    stmt = select(RiskReport).where(RiskReport.document_id == document_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()

    from google.genai.errors import ClientError
    try:
        if doc.strategy == "rag":
            # Oversized doc: build the report from retrieved clauses, not whole-file attachment.
            from app.services.risk.rag_report import generate_rag_report_data
            gen = await generate_rag_report_data(
                db, document_id, model=use_model, max_output_tokens=4000
            )
        else:
            file_name = await _ensure_uploaded(db, doc)
            try:
                gen = await get_gemini_files().answer(
                    file_name=file_name,
                    question=question,
                    model=use_model,
                    system_prompt=RISK_SYSTEM_PROMPT,
                    schema=RISK_REPORT_SCHEMA,
                    max_output_tokens=4000,
                )
            except ClientError as e:
                if e.code in (403, 404):
                    logger.warning(f"Gemini file {file_name} not found/accessible for report (code {e.code}). Re-uploading...")
                    file_name = await _ensure_uploaded(db, doc, force_reupload=True)
                    gen = await get_gemini_files().answer(
                        file_name=file_name,
                        question=question,
                        model=use_model,
                        system_prompt=RISK_SYSTEM_PROMPT,
                        schema=RISK_REPORT_SCHEMA,
                        max_output_tokens=4000,
                    )
                else:
                    raise
    except Exception as e:
        logger.error(f"Failed to generate risk report for {document_id}: {e}")
        # Update or create a failed report entry so we don't keep polling
        if not report:
            report = RiskReport(document_id=doc.id)
            db.add(report)
        report.status = "failed"
        report.error_msg = str(e)
        report.overall_risk_score = "unknown"
        await db.commit()
        return report

    data: dict[str, Any] = gen.data
    risks: list[dict[str, Any]] = data.get("risks", [])

    # Compute quick counts
    high_count = sum(1 for r in risks if r.get("severity") == "high")
    medium_count = sum(1 for r in risks if r.get("severity") == "medium")
    low_count = sum(1 for r in risks if r.get("severity") == "low")

    if not report:
        report = RiskReport(document_id=doc.id)
        db.add(report)
        
    report.status = "ready"
    report.overall_risk_score = data.get("overall_risk_score", "unknown")
    report.summary = data.get("summary", "")
    report.risks = risks
    report.risk_count_high = high_count
    report.risk_count_medium = medium_count
    report.risk_count_low = low_count
    report.model = gen.model
    report.token_usage = gen.token_usage
    report.error_msg = None

    await db.commit()
    await db.refresh(report)
    return report
