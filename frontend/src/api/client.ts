const BASE = (import.meta.env.VITE_API_URL as string) ?? "http://localhost:8000";

// Dev auth stub — matches the backend's X-User-Email header dependency.
const authHeaders = { "X-User-Email": "dev@local" };

export interface DocumentSummary {
  id: string;
  filename: string;
  status: string;
  mime_type?: string;
  report_status?: string;
  page_count: number | null;
}

/** Fetch the raw document file (auth-scoped) and return an object URL for in-app preview.
 *  The caller is responsible for URL.revokeObjectURL() when done. */
export async function fetchDocumentObjectUrl(id: string): Promise<string> {
  const res = await fetch(`${BASE}/documents/${id}/file`, { headers: authHeaders });
  if (!res.ok) throw new Error("Failed to load document file");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/** Matches the shape returned by backend _build_citations */
export interface Citation {
  claim_text?: string;
  quote?: string;
  page?: number;
  section?: string;
  exceptions?: string[];
  polarity?: "affirmative" | "negative";
  // legacy fields (kept for compatibility)
  chunk_id?: string;
  cited_span?: string;
  verified?: boolean;
}

export interface TokenUsage {
  input?: number;
  output?: number;
  cached?: number;
}

export interface AnswerResponse {
  id: string;
  answer: string;
  citations: Citation[];
  answerable: boolean | null;
  confidence: string | null;
  escalated: boolean;
  token_usage?: TokenUsage | null;
}

export async function uploadDocument(file: File): Promise<{ document_id: string; status: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/documents/upload`, {
    method: "POST",
    headers: authHeaders,
    body: form,
  });
  if (!res.ok) throw new Error("upload failed");
  return res.json();
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const res = await fetch(`${BASE}/documents`, { headers: authHeaders });
  return res.json();
}

export async function getDocument(id: string): Promise<DocumentSummary & { error_msg?: string }> {
  const res = await fetch(`${BASE}/documents/${id}`, { headers: authHeaders });
  return res.json();
}

export async function createConversation(documentId: string): Promise<{ id: string }> {
  const res = await fetch(`${BASE}/conversations`, {
    method: "POST",
    headers: { ...authHeaders, "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId }),
  });
  return res.json();
}

export async function ask(
  conversationId: string,
  question: string,
  tier?: string,
): Promise<AnswerResponse> {
  const res = await fetch(`${BASE}/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { ...authHeaders, "Content-Type": "application/json" },
    body: JSON.stringify({ question, tier }),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || "ask failed");
  }
  return res.json();
}

export interface RiskItem {
  category: string;
  severity: "high" | "medium" | "low";
  clause_name?: string;
  risk_description: string;
  quoted_text: string;
  page?: number;
  section?: string;
  recommendation: string;
}

export interface RiskReport {
  status: string;
  overall_risk_score?: "high" | "medium" | "low";
  summary?: string;
  risks?: RiskItem[];
  risk_count_high?: number;
  risk_count_medium?: number;
  risk_count_low?: number;
  model?: string;
  token_usage?: TokenUsage;
  error_msg?: string;
}

export async function getRiskReport(documentId: string): Promise<RiskReport> {
  const res = await fetch(`${BASE}/documents/${documentId}/report`, { headers: authHeaders });
  return res.json();
}

export async function regenerateRiskReport(documentId: string, tier?: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/documents/${documentId}/report/regenerate`, {
    method: "POST",
    headers: { ...authHeaders, "Content-Type": "application/json" },
    body: JSON.stringify({ tier }),
  });
  if (!res.ok) throw new Error("regenerate failed");
  return res.json();
}
