import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { listDocuments, type Citation, type DocumentSummary } from "./api/client";
import { ChatPanel } from "./features/chat/ChatPanel";
import { UploadPanel } from "./features/upload/UploadPanel";
import { DocumentViewer } from "./features/viewer/DocumentViewer";

export function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);

  // Poll so ingestion status (processing → ready) updates live.
  const { data: documents = [] } = useQuery({
    queryKey: ["documents"],
    queryFn: listDocuments,
    refetchInterval: 3000,
  });

  const selected: DocumentSummary | null =
    documents.find((d) => d.id === selectedId) ?? null;

  return (
    <div className="app">
      <div className="topbar">
        <strong>Contract Analyzer</strong>
        <UploadPanel />
        <select
          value={selectedId ?? ""}
          onChange={(e) => setSelectedId(e.target.value || null)}
        >
          <option value="">Select document…</option>
          {documents.map((d) => (
            <option key={d.id} value={d.id}>
              {d.filename} ({d.status})
            </option>
          ))}
        </select>
      </div>
      <div className="split">
        <div className="viewer">
          <DocumentViewer document={selected} activeCitation={activeCitation} />
        </div>
        <ChatPanel
          documentId={selectedId}
          documentReady={selected?.status === "ready"}
          onCiteClick={setActiveCitation}
        />
      </div>
    </div>
  );
}
