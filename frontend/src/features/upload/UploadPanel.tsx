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
    <label className="muted">
      {busy ? "Uploading…" : "Upload contract (PDF/DOCX)"}
      <input type="file" accept=".pdf,.docx" onChange={onFile} disabled={busy} hidden />
    </label>
  );
}
