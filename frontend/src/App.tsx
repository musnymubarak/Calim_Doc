import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { listDocuments, type Citation, type DocumentSummary } from "./api/client";
import { ResizeHandle } from "./components/ResizeHandle";
import { ChatPanel } from "./features/chat/ChatPanel";
import { RiskReportPanel } from "./features/report/RiskReportPanel";
import { UploadPanel } from "./features/upload/UploadPanel";
import { DocumentViewer } from "./features/viewer/DocumentViewer";

const clamp = (v: number, min: number, max: number) => Math.min(Math.max(v, min), max);

// Persisted, clamped panel width with a setter that accepts a drag delta.
function usePanelWidth(key: string, initial: number, min: number, max: number) {
  const [width, setWidth] = useState<number>(() => {
    const saved = Number(localStorage.getItem(key));
    return saved ? clamp(saved, min, max) : initial;
  });
  useEffect(() => {
    localStorage.setItem(key, String(width));
  }, [key, width]);
  const resizeBy = (delta: number) => setWidth((w) => clamp(w + delta, min, max));
  return [width, resizeBy] as const;
}

export function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [activeTab, setActiveTab] = useState<"chat" | "report">("chat");

  // Drag-resizable panel widths (persisted). Sidebar grows when dragged right;
  // the chat panel grows when its handle is dragged left, so its delta is negated.
  const [sidebarWidth, resizeSidebar] = usePanelWidth("calim:sidebarW", 256, 200, 460);
  const [chatWidth, resizeChat] = usePanelWidth("calim:chatW", 420, 320, 760);

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
      {/* ─── Side navigation ───────────────────────────────────────── */}
      <aside className="sidebar" style={{ width: sidebarWidth }}>
        <div className="sidebar-brand">
          <div className="sidebar-brand-icon">
            <span className="material-symbols-outlined">account_balance</span>
          </div>
          <div>
            <h1>Calim Doc</h1>
          </div>
        </div>

        {/* ─── Uploaded documents ──────────────────────────────────── */}
        <nav className="sidebar-docs">
          <div className="sidebar-section-label">Documents</div>
          {documents.length === 0 ? (
            <div className="sidebar-docs-empty">
              No contracts yet. Upload one to get started.
            </div>
          ) : (
            documents.map((d) => (
              <button
                key={d.id}
                className={`doc-item ${d.id === selectedId ? "active" : ""}`}
                onClick={() => {
                  setSelectedId(d.id);
                  setActiveCitation(null);
                }}
                title={d.filename}
              >
                <span className="material-symbols-outlined sm">description</span>
                <span className="doc-item-name">{d.filename}</span>
                <span className={`doc-item-status ${d.status}`}>{d.status}</span>
              </button>
            ))
          )}
        </nav>

        <div className="sidebar-footer">
          <UploadPanel />
        </div>
      </aside>

      <ResizeHandle onResize={resizeSidebar} aria-label="Resize sidebar" />

      {/* ─── Main column ───────────────────────────────────────────── */}
      <div className="main">
        <header className="topbar">
          <div className="topnav-title">Contract Intelligence</div>
          <div className="topbar-divider"></div>
          <nav className="topnav-links">
            <a
              className={`topnav-link ${activeTab === "chat" ? "active" : ""}`}
              onClick={() => setActiveTab("chat")}
            >
              Analysis
            </a>
            <a
              className={`topnav-link ${activeTab === "report" ? "active" : ""}`}
              onClick={() => setActiveTab("report")}
            >
              Risk
            </a>
          </nav>

          <div className="topbar-spacer"></div>

          <select
            className="doc-select"
            value={selectedId ?? ""}
            onChange={(e) => {
              setSelectedId(e.target.value || null);
              setActiveCitation(null);
            }}
          >
            <option value="">Select a contract…</option>
            {documents.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename} ({d.status})
              </option>
            ))}
          </select>
        </header>

        <div className="split">
          <main className="viewer">
            <DocumentViewer document={selected} activeCitation={activeCitation} />
          </main>
          <ResizeHandle
            onResize={(dx) => resizeChat(-dx)}
            aria-label="Resize chat panel"
          />
          <aside className="chat-container" style={{ width: chatWidth }}>
            {selected ? (
              <div className="tab-bar">
                <button
                  className={`tab-btn ${activeTab === "chat" ? "active" : ""}`}
                  onClick={() => setActiveTab("chat")}
                >
                  <span className="material-symbols-outlined sm">forum</span>
                  Chat
                </button>
                <button
                  className={`tab-btn ${activeTab === "report" ? "active" : ""}`}
                  onClick={() => setActiveTab("report")}
                >
                  <span className="material-symbols-outlined sm">shield</span>
                  Risk Report
                  {selected.report_status === "ready" && <span className="tab-badge ready"></span>}
                </button>
              </div>
            ) : null}

            <div className="tab-content">
              {activeTab === "chat" ? (
                <ChatPanel
                  documentId={selectedId}
                  documentReady={selected?.status === "ready"}
                  onCiteClick={setActiveCitation}
                />
              ) : (
                selectedId && <RiskReportPanel documentId={selectedId} onCiteClick={setActiveCitation} />
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
