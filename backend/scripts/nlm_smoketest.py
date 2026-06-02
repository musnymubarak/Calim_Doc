"""Standalone smoke test for the NotebookLM server integration (no Postgres/FastAPI needed).

Mirrors the exact request shapes in app/services/notebooklm/client.py against a running server,
so a pass means client.py's contract is correct. Uses only the stdlib.

Usage:
    python backend/scripts/nlm_smoketest.py [absolute_path_to_document]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://localhost:3000"
DEFAULT_DOC = r"C:\Users\musny\Desktop\Hashnate\Calim_Document_Analyzis\data\sample_contract.txt"


def _post(path: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(path: str, timeout: int = 30) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> None:
    doc = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOC

    print("== /health ==")
    print(json.dumps(_get("/health"), indent=2))

    print("\n== POST /notebooks/create ==")
    nb = _post("/notebooks/create", {"name": "smoketest-contract", "show_browser": False})
    print(json.dumps(nb, indent=2))
    data = nb.get("data", nb)
    notebook_url = data.get("notebook_url") or data.get("url")
    print("notebook_url:", notebook_url)
    if not notebook_url:
        print("!! no notebook_url — stopping"); return

    print("\n== POST /content/sources (file_path) ==")
    src = _post("/content/sources", {
        "source_type": "file", "file_path": doc, "notebook_url": notebook_url,
    })
    print(json.dumps(src, indent=2))

    print("\n...waiting 15s for source processing...")
    time.sleep(15)

    print("\n== POST /ask ==")
    ans = _post("/ask", {
        "question": "What is the limitation of liability cap, and what are the exceptions to it?",
        "notebook_url": notebook_url,
        "source_format": "inline",
    })
    print(json.dumps(ans, indent=2)[:3000])


if __name__ == "__main__":
    main()
