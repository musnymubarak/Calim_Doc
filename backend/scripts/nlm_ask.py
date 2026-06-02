"""Ask-only test against an EXISTING NotebookLM notebook (bypasses the broken create flow).

Usage:
    python backend/scripts/nlm_ask.py "<notebook_url>" "<question>"

notebook_url = the URL from your browser's address bar while viewing the notebook, e.g.
https://notebooklm.google.com/notebook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://localhost:3000"


def _post(path: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python nlm_ask.py "<notebook_url>" ["<question>"]'); return
    notebook_url = sys.argv[1]
    question = sys.argv[2] if len(sys.argv) > 2 else (
        "What is the limitation of liability cap, and what are the exceptions to it?"
    )
    print(f"asking: {question}\nnotebook: {notebook_url}\n")
    ans = _post("/ask", {
        "question": question, "notebook_url": notebook_url, "source_format": "inline",
    })
    print(json.dumps(ans, indent=2)[:4000])


if __name__ == "__main__":
    main()
