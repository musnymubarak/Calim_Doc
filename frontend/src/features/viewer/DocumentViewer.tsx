import { useEffect, useState } from "react";
import { fetchDocumentObjectUrl, type Citation, type DocumentSummary } from "../../api/client";

interface Props {
  document: DocumentSummary | null;
  activeCitation: Citation | null;
}

const isPdf = (d: DocumentSummary) =>
  (d.mime_type ?? "").includes("pdf") || d.filename.toLowerCase().endsWith(".pdf");

export function DocumentViewer({ document, activeCitation }: Props) {
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);

  // Load the raw file (auth-scoped blob) whenever the selected document changes.
  useEffect(() => {
    setFileUrl(null);
    setLoadError(false);
    if (!document || !isPdf(document)) return;

    let revoked: string | null = null;
    let cancelled = false;
    fetchDocumentObjectUrl(document.id)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        revoked = url;
        setFileUrl(url);
      })
      .catch(() => !cancelled && setLoadError(true));

    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [document?.id]);

  if (!document) {
    return (
      <div className="viewer-empty">
        <div className="viewer-empty-icon">📄</div>
        <h3>No Contract Selected</h3>
        <p className="muted">Upload a contract or choose one from the list to begin analysis.</p>
      </div>
    );
  }

  const page = activeCitation?.page ?? 1;
  // #page jumps the native PDF viewer to the cited page; keying on it forces re-navigation.
  const pdfSrc = fileUrl ? `${fileUrl}#page=${page}&zoom=page-width&view=FitH` : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="viewer-header">
        <h2 className="viewer-filename">{document.filename}</h2>
        <div className="viewer-meta">
          <span className={`status-badge ${document.status}`}>
            <span className="status-dot"></span>
            {document.status}
          </span>
          {document.page_count && (
            <>
              <span>•</span>
              <span>{document.page_count} pages</span>
            </>
          )}
        </div>
      </div>

      {/* Citation reference banner — shown alongside the preview when a citation is active. */}
      {activeCitation && (
        <div className="citation-banner">
          <div className="citation-banner-label">
            Active Reference • Page {activeCitation.page ?? "?"}
            {activeCitation.section && ` • Section: ${activeCitation.section}`}
          </div>
          {activeCitation.quote && (
            <div className="citation-banner-text">"{activeCitation.quote}"</div>
          )}
          {activeCitation.claim_text && (
            <div className="citation-banner-claim">
              Supports claim: "{activeCitation.claim_text}"
            </div>
          )}
        </div>
      )}

      <div className="viewer-body viewer-body--preview">
        {pdfSrc ? (
          <iframe
            key={page}
            className="viewer-pdf-frame"
            src={pdfSrc}
            title={document.filename}
          />
        ) : loadError ? (
          <div className="viewer-pdf-placeholder">
            <h4>Preview unavailable</h4>
            <p style={{ maxWidth: 360, fontSize: 13 }}>
              The original file could not be loaded. Citations and answers still work in the
              assistant pane.
            </p>
          </div>
        ) : isPdf(document) ? (
          <div className="viewer-pdf-placeholder">
            <div className="viewer-spinner" />
            <p style={{ fontSize: 13 }}>Loading document preview…</p>
          </div>
        ) : (
          <div className="viewer-pdf-placeholder">
            <h4>Preview not available for this file type</h4>
            <p style={{ maxWidth: 360, fontSize: 13 }}>
              In-app preview supports PDFs. Citations and evidence still appear above.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
