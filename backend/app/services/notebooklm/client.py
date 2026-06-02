"""HTTP client for the NotebookLM automation server.

Targets roomi-fields/notebooklm-mcp's REST API (the one that exposes an HTTP server in front
of browser-driven NotebookLM). Routes/envelope below match its documented API
(https://github.com/roomi-fields/notebooklm-mcp), port 3000, `{success, data}` envelope.

Confirmed against the server source (src/http-wrapper.ts):
  - /ask accepts `notebook_url` directly — no library-slug resolution needed.
  - /content/sources takes JSON {source_type, file_path, url, text, notebook_url} — NOT a
    multipart upload. For a local file pass source_type='file' + file_path, and the server
    reads that path from ITS OWN filesystem. ⇒ the NotebookLM server must see the file on disk:
    in Docker, mount the shared files volume into the notebooklm service at the SAME path the
    backend uses (/data/files).
"""
from __future__ import annotations

import httpx

from app.config import settings

_EP_HEALTH = "/health"
_EP_CREATE_NOTEBOOK = "/notebooks/create"     # POST {name, show_browser} -> data.notebook_url
_EP_LIST_NOTEBOOKS = "/notebooks"             # GET -> data.notebooks[].{id,url,name}
_EP_ADD_SOURCE = "/content/sources"           # POST -> {success, sourceName, status}
_EP_ASK = "/ask"                              # POST {question, notebook_id, source_format} -> data


class NotebookLMError(RuntimeError):
    pass


class NotebookLMClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self._base = (base_url or settings.notebooklm_api_url).rstrip("/")
        self._timeout = timeout or settings.notebooklm_request_timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base, timeout=self._timeout)

    @staticmethod
    def _unwrap(resp: httpx.Response) -> dict:
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict) and body.get("success") is False:
            raise NotebookLMError(str(body))
        # roomi-fields wraps most payloads in {success, data}; some (add_source) are flat.
        return body.get("data", body) if isinstance(body, dict) else {}

    async def health(self) -> bool:
        try:
            async with self._client() as c:
                data = self._unwrap(await c.get(_EP_HEALTH))
            return bool(data.get("authenticated", True))
        except httpx.HTTPError:
            return False

    async def create_notebook(self, name: str) -> str:
        """Returns the notebook_url (the identifier roomi-fields hands back on creation)."""
        async with self._client() as c:
            data = self._unwrap(await c.post(
                _EP_CREATE_NOTEBOOK, json={"name": name, "show_browser": False}
            ))
        url = data.get("notebook_url") or data.get("url")
        if not url:
            raise NotebookLMError(f"create_notebook returned no notebook_url: {data}")
        return str(url)

    async def add_source(self, notebook_url: str, file_path: str) -> str:
        """Add a local file as a source. The server reads `file_path` from ITS OWN filesystem
        (not an upload stream), so the path must be visible to the NotebookLM server — share
        the files volume in Docker. Returns the source name/id."""
        async with self._client() as c:
            resp = await c.post(
                _EP_ADD_SOURCE,
                json={"source_type": "file", "file_path": file_path,
                      "notebook_url": notebook_url},
            )
            resp.raise_for_status()
            body = resp.json()
        if isinstance(body, dict) and body.get("success") is False:
            raise NotebookLMError(str(body))
        src = body.get("sourceName") or body.get("source_id") or body.get("id")
        if not src:
            raise NotebookLMError(f"add_source returned no source id: {body}")
        return str(src)

    async def ask(self, notebook_url: str, question: str, source_format: str = "inline") -> dict:
        """Ask a grounded question (passes notebook_url directly). Returns {'answer','citations'}.

        Citations come as data.sources.citations[] = {marker, number, sourceText}.
        """
        async with self._client() as c:
            data = self._unwrap(await c.post(
                _EP_ASK,
                json={"question": question, "notebook_url": notebook_url,
                      "source_format": source_format},
            ))
        return {
            "answer": data.get("answer", ""),
            "citations": (data.get("sources") or {}).get("citations", []),
        }


_client: NotebookLMClient | None = None


def get_notebooklm() -> NotebookLMClient:
    global _client
    if _client is None:
        _client = NotebookLMClient()
    return _client
