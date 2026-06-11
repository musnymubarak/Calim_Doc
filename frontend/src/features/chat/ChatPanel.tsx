import { useEffect, useState, useRef } from "react";
import { ask, createConversation, type AnswerResponse, type Citation, type TokenUsage } from "../../api/client";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  escalated?: boolean;
  confidence?: string | null;
  token_usage?: TokenUsage | null;
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
  const [expandedClaims, setExpandedClaims] = useState<Record<number, boolean>>({});

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  // New conversation whenever the selected document changes.
  useEffect(() => {
    setMessages([]);
    setConversationId(null);
    if (documentId) {
      createConversation(documentId).then((c) => setConversationId(c.id));
    }
  }, [documentId]);

  async function send(textToSend?: string) {
    const queryText = textToSend || input;
    if (!queryText.trim() || !conversationId) return;

    if (!textToSend) setInput("");

    setMessages((m) => [...m, { role: "user", content: queryText.trim() }]);
    setBusy(true);

    try {
      const res: AnswerResponse = await ask(conversationId, queryText.trim());
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.answer,
          citations: res.citations,
          escalated: res.escalated,
          confidence: res.confidence,
          token_usage: res.token_usage,
        },
      ]);
    } catch (err: any) {
      console.error(err);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: err.message === "ask failed"
            ? "Sorry, I encountered an error processing that question. Please try again."
            : `Error: ${err.message}`,
          confidence: "low",
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  const toggleClaims = (index: number) => {
    setExpandedClaims((prev) => ({
      ...prev,
      [index]: !prev[index],
    }));
  };

  // Helper to parse message content if it was stored/returned as raw JSON.
  function renderMessageContent(msg: ChatMessage, msgIndex: number) {
    let displayAnswer = msg.content;
    let displayConfidence = msg.confidence;
    let displayEscalated = msg.escalated;
    let displayCitations = msg.citations || [];

    // Check if content itself is JSON
    if (msg.content && msg.content.trim().startsWith("{")) {
      try {
        const parsed = JSON.parse(msg.content);
        if (parsed && typeof parsed === "object") {
          displayAnswer = parsed.answer || "";
          if (parsed.confidence) displayConfidence = parsed.confidence;
          if (parsed.escalated !== undefined) displayEscalated = parsed.escalated;

          if (parsed.claims && Array.isArray(parsed.claims)) {
            displayCitations = parsed.claims.map((c: any) => ({
              claim_text: c.claim_text,
              quote: c.cited_quote || c.quote,
              page: c.page,
              section: c.section,
              exceptions: c.exceptions,
              polarity: c.polarity,
            }));
          } else if (parsed.citations && Array.isArray(parsed.citations)) {
            displayCitations = parsed.citations;
          }
        }
      } catch (e) {
        // Fallback to raw string
      }
    }

    if (msg.role === "user") {
      return <div className="answer-body">{displayAnswer}</div>;
    }

    const isClaimsOpen = expandedClaims[msgIndex] !== false; // default to open

    return (
      <>
        {/* Main Answer text */}
        <div className="answer-body">{displayAnswer}</div>

        {/* Status badges & Token usage */}
        {(displayConfidence || displayEscalated || msg.token_usage) && (
          <div className="answer-badges">
            {displayConfidence && (
              <span className={`badge badge-${displayConfidence.toLowerCase()}`}>
                {displayConfidence.toUpperCase()} CONFIDENCE
              </span>
            )}
            {displayEscalated && (
              <span className="badge badge-escalated">
                ESCALATED
              </span>
            )}
            {msg.token_usage && (
              <span className="badge" style={{ background: "var(--bg-hover)", color: "var(--text-secondary)", border: "1px solid var(--border-active)" }}>
                Tokens: {msg.token_usage.input?.toLocaleString() ?? 0} in | {msg.token_usage.output?.toLocaleString() ?? 0} out
                {msg.token_usage.cached ? ` (${msg.token_usage.cached.toLocaleString()} cached)` : ""}
              </span>
            )}
          </div>
        )}

        {/* Claims & citations accordion */}
        {displayCitations && displayCitations.length > 0 && (
          <div className="claims-section">
            <div className="claims-header" onClick={() => toggleClaims(msgIndex)}>
              <span>Evidence & Citations</span>
              <span className="claims-header-count">{displayCitations.length}</span>
              <span className={`claims-header-chevron ${isClaimsOpen ? "open" : ""}`}>▼</span>
            </div>

            {isClaimsOpen && (
              <div className="claims-list">
                {displayCitations.map((c, j) => (
                  <div key={j} className="claim-card" onClick={() => onCiteClick(c)}>
                    {c.claim_text && (
                      <div className="claim-text">{c.claim_text}</div>
                    )}

                    {c.polarity && (
                      <span className={`claim-polarity ${c.polarity}`}>
                        {c.polarity}
                      </span>
                    )}

                    {c.quote && (
                      <div className="claim-quote">
                        <span className="claim-quote-icon">“</span>
                        <div className="claim-quote-text">{c.quote}</div>
                      </div>
                    )}

                    <div className="claim-footer">
                      <span className="claim-page">
                        ↪ Page {c.page ?? "?"}
                      </span>
                      {c.section && (
                        <span className="claim-section">
                          Section: {c.section}
                        </span>
                      )}
                      {c.exceptions && c.exceptions.length > 0 && (
                        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", width: "100%", marginTop: 4 }}>
                          {c.exceptions.map((ex, k) => (
                            <span key={k} className="claim-exception">
                              ⚠ Carve-out: {ex}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </>
    );
  }

  // Quick Action Pills
  const quickActions = [
    "Give a brief summary about this document",
    "What are the main liabilities and risk factors?",
    "List all terminations and notice periods",
  ];

  return (
    <div className="chat">
      <div className="chat-header">
        <div>
          <div className="chat-title">AI Legal Assistant</div>
          <div className="chat-subtitle">Grounded in the selected document</div>
        </div>
      </div>

      <div className="messages">
        {messages.length === 0 && (
          <div className="messages-empty">
            <div className="messages-empty-icon"></div>
            <h3>Contract Q&A</h3>
            <p>Ask details about liabilities, governing law, terminations, or dates.</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="msg-meta">
              {m.role === "user" ? "You" : "Calim AI"}
            </div>
            <div className="bubble">
              {renderMessageContent(m, i)}
            </div>
          </div>
        ))}

        {busy && (
          <div className="msg assistant">
            <div className="msg-meta">Calim AI</div>
            <div className="bubble">
              <div className="typing-indicator">
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {messages.length === 0 && conversationId && documentReady && (
        <div className="quick-actions">
          {quickActions.map((act, i) => (
            <button
              key={i}
              className="quick-pill"
              onClick={() => send(act)}
              disabled={busy}
            >
              {act}
            </button>
          ))}
        </div>
      )}

      <div className="composer">
        <div className="composer-input-wrap">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder={
              !documentId
                ? "Select a document first..."
                : documentReady
                  ? "Ask a question about the contract..."
                  : "Waiting for document to finish processing..."
            }
            disabled={busy || !conversationId || !documentReady}
          />
        </div>
        <button
          className="send-btn"
          onClick={() => send()}
          disabled={busy || !conversationId || !documentReady || !input.trim()}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  );
}
