import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { uploadDocument } from "../../api/client";

export function UploadPanel() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      await uploadDocument(file);
      await qc.invalidateQueries({ queryKey: ["documents"] });
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <label className={`upload-btn ${busy ? "busy" : ""}`}>
      {busy ? (
        <>
          <span className="status-dot" style={{ animation: "pulse 1.4s ease-in-out infinite", background: "currentColor" }}></span>
          Uploading…
        </>
      ) : (
        <>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          Upload contract
        </>
      )}
      <input type="file" accept=".pdf,.docx" onChange={onFile} disabled={busy} hidden />
    </label>
  );
}
