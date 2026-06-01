import { useEffect, useState } from "react";
import { ask, createConversation, type AnswerResponse, type Citation } from "../../api/client";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  escalated?: boolean;
  confidence?: string | null;
}

interface Props {
  documentId: string | null;
  documentReady: boolean;
  onCiteClick: (c: Citation) => void;
}

export function ChatPanel({ documentId, documentReady, onCiteClick }: Props) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  // New conversation whenever the selected document changes.
  useEffect(() => {
    setMessages([]);
    setConversationId(null);
    if (documentId) createConversation(documentId).then((c) => setConversationId(c.id));
  }, [documentId]);

  async function send() {
    if (!input.trim() || !conversationId) return;
    const question = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: question }]);
    setBusy(true);
    try {
      const res: AnswerResponse = await ask(conversationId, question);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.answer,
          citations: res.citations,
          escalated: res.escalated,
          confidence: res.confidence,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat">
      <div className="messages">
        {messages.length === 0 && <div className="muted">Ask a question about the contract.</div>}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">
              {m.content}
              {m.role === "assistant" && (
                <div>
                  {m.confidence && <span className="muted"> · {m.confidence} confidence</span>}
                  {m.escalated && <span className="muted"> · escalated</span>}
                  {m.citations?.map((c, j) => (
                    <div key={j} className="citation" onClick={() => onCiteClick(c)}>
                      ↪ p.{c.page ?? "?"} {c.section ?? ""} {c.verified === false && "⚠"}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder={documentReady ? "Ask…" : "Waiting for document to finish processing…"}
          disabled={busy || !conversationId}
        />
        <button onClick={send} disabled={busy || !conversationId}>
          Send
        </button>
      </div>
    </div>
  );
}
