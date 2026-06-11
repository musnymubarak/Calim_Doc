import asyncio
from app.db.session import SessionLocal
from app.services.gemini_files.client import get_gemini_files
from app.services.risk.schemas import RISK_REPORT_SCHEMA, RISK_SYSTEM_PROMPT
from app.models.document import Document
import uuid

async def main():
    async with SessionLocal() as db:
        # get any ready document
        result = await db.execute("SELECT id, gemini_file_name FROM documents WHERE status='ready' LIMIT 1")
        row = result.fetchone()
        if not row:
            print("No ready document found.")
            return
        doc_id, file_name = row
        print(f"Using file: {file_name}")

        try:
            print("Calling answer()...")
            gen = await get_gemini_files().answer(
                file_name=file_name,
                question="Analyze this contract for risks.",
                model="gemini-2.5-flash",
                system_prompt=RISK_SYSTEM_PROMPT,
                schema=RISK_REPORT_SCHEMA,
                max_output_tokens=4000,
            )
            print("Success!")
            print(gen.data)
        except Exception as e:
            import traceback
            traceback.print_exc()

asyncio.run(main())
