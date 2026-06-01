import type { Citation, DocumentSummary } from "../../api/client";

interface Props {
  document: DocumentSummary | null;
  activeCitation: Citation | null;
}

/**
 * Document viewer. Scaffold renders status + the active citation target.
 * TODO: add a backend file-serving endpoint, render with react-pdf, and draw a bbox
 * highlight overlay for `activeCitation` (page + bbox from the chunk).
 */
export function DocumentViewer({ document, activeCitation }: Props) {
  if (!document) return <div className="muted">Upload or select a document to begin.</div>;

  return (
    <div>
      <h3>{document.filename}</h3>
      <p className="muted">
        Status: {document.status}
        {document.page_count ? ` · ${document.page_count} pages` : ""}
      </p>
      {activeCitation && (
        <div className="muted">
          Jump to: page {activeCitation.page ?? "?"} · {activeCitation.section ?? "—"}
          {activeCitation.verified === false && " · ⚠ unverified citation"}
        </div>
      )}
      <div className="muted" style={{ marginTop: 24 }}>
        [PDF.js viewer renders here once a file-serving endpoint exists]
      </div>
    </div>
  );
}
