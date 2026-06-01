const BASE = (import.meta.env.VITE_API_URL as string) ?? "http://localhost:8000";

// Dev auth stub — matches the backend's X-User-Email header dependency.
const authHeaders = { "X-User-Email": "dev@local" };

export interface DocumentSummary {
  id: string;
  filename: string;
  status: string;
  page_count: number | null;
}

export interface Citation {
  chunk_id: string;
  page?: number;
  section?: string;
  cited_span?: string;
  verified?: boolean;
}

export interface AnswerResponse {
  id: string;
  answer: string;
  citations: Citation[];
  answerable: boolean | null;
  confidence: string | null;
  escalated: boolean;
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
  if (!res.ok) throw new Error("ask failed");
  return res.json();
}
