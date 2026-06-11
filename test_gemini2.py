import asyncio
from app.services.gemini_files.client import get_gemini_files
from app.services.risk.schemas import RISK_REPORT_SCHEMA, RISK_SYSTEM_PROMPT

async def main():
    client = get_gemini_files()
    
    # create a dummy text file
    with open("dummy.txt", "w") as f:
        f.write("This is a dummy contract. It has no risks.")
        
    print("Uploading...")
    f = await client.upload("dummy.txt", "text/plain")
    print(f"Uploaded: {f.name}")
    
    try:
        print("Calling answer() with gemini-2.5-flash...")
        gen = await client.answer(
            file_name=f.name,
            question="Analyze this contract for risks.",
            model="gemini-2.5-flash",
            system_prompt=RISK_SYSTEM_PROMPT,
            schema=RISK_REPORT_SCHEMA,
            max_output_tokens=4000,
        )
        print("Success 2.5!")
    except Exception as e:
        print(f"Error 2.5: {e}")

    try:
        print("Calling answer() with gemini-2.0-flash...")
        gen = await client.answer(
            file_name=f.name,
            question="Analyze this contract for risks.",
            model="gemini-2.0-flash",
            system_prompt=RISK_SYSTEM_PROMPT,
            schema=RISK_REPORT_SCHEMA,
            max_output_tokens=4000,
        )
        print("Success 2.0!")
    except Exception as e:
        print(f"Error 2.0: {e}")

asyncio.run(main())
