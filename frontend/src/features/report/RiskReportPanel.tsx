import { useEffect, useState } from "react";
import { getRiskReport, regenerateRiskReport, RiskReport, RiskItem } from "../../api/client";

interface RiskReportPanelProps {
  documentId: string;
  onCiteClick?: (citation: { page?: number; section?: string; claim_text?: string }) => void;
}

export function RiskReportPanel({ documentId, onCiteClick }: RiskReportPanelProps) {
  const [report, setReport] = useState<RiskReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let timer: number;

    const fetchReport = async () => {
      try {
        const data = await getRiskReport(documentId);
        if (!active) return;
        setReport(data);

        // Poll if still pending or generating
        if (data.status === "pending" || data.status === "generating") {
          timer = window.setTimeout(fetchReport, 3000);
        }
      } catch (err: any) {
        if (!active) return;
        setError(err.message || "Failed to load risk report.");
      }
    };

    setReport(null);
    setError(null);
    fetchReport();

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [documentId]);

  const handleRegenerate = async (tier: "fast" | "accurate") => {
    try {
      await regenerateRiskReport(documentId, tier);
      setReport({ status: "generating" });
    } catch (err: any) {
      setError(err.message || "Failed to regenerate report.");
    }
  };

  if (error) {
    return (
      <div className="report-panel error">
        <h3>Error Loading Report</h3>
        <p>{error}</p>
        <button onClick={() => setReport({ status: "pending" })}>Retry</button>
      </div>
    );
  }

  if (!report || report.status === "pending" || report.status === "generating") {
    return (
      <div className="report-panel loading">
        <div className="shimmer-header"></div>
        <div className="shimmer-summary"></div>
        <div className="shimmer-card"></div>
        <div className="shimmer-card"></div>
        <p className="loading-text">
          {report?.status === "generating" ? "Generating report..." : "Waiting for report generation..."}
        </p>
      </div>
    );
  }

  if (report.status === "failed") {
    return (
      <div className="report-panel error">
        <h3>Report Generation Failed</h3>
        <p>{report.error_msg}</p>
        <button onClick={() => handleRegenerate("fast")}>Retry</button>
      </div>
    );
  }

  return (
    <div className="report-panel">
      <div className="report-header">
        <div className="score-badge" data-score={report.overall_risk_score}>
          Overall Risk: {report.overall_risk_score?.toUpperCase()}
        </div>
        <div className="risk-counts">
          <span className="count high">{report.risk_count_high} High</span>
          <span className="count medium">{report.risk_count_medium} Medium</span>
          <span className="count low">{report.risk_count_low} Low</span>
        </div>
        <div className="regenerate-actions">
          <button className="secondary" onClick={() => handleRegenerate("accurate")}>
            Deep Analysis (Pro)
          </button>
        </div>
      </div>

      <div className="report-summary">
        <h4>Executive Summary</h4>
        <p>{report.summary}</p>
      </div>

      <div className="risk-items">
        {report.risks?.map((risk, idx) => (
          <RiskCard key={idx} risk={risk} onCiteClick={onCiteClick} />
        ))}
        {(!report.risks || report.risks.length === 0) && (
          <p className="no-risks">No significant risks identified.</p>
        )}
      </div>
    </div>
  );
}

function RiskCard({ risk, onCiteClick }: { risk: RiskItem; onCiteClick?: RiskReportPanelProps["onCiteClick"] }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="risk-card" data-severity={risk.severity}>
      <div className="risk-card-header" onClick={() => setExpanded(!expanded)}>
        <div className="risk-card-title">
          <span className="severity-dot"></span>
          <span className="category-tag">{risk.category}</span>
          <h5>{risk.clause_name || risk.category}</h5>
        </div>
        <span className="expand-icon">{expanded ? "▼" : "▶"}</span>
      </div>
      
      <div className="risk-card-body">
        <p className="risk-desc">{risk.risk_description}</p>
        
        {expanded && (
          <div className="risk-card-expanded">
            {risk.quoted_text && (
              <blockquote className="claim-quote">
                {risk.quoted_text}
              </blockquote>
            )}
            
            <div className="risk-meta">
              {risk.page !== undefined && (
                <button 
                  className="cite-link"
                  onClick={() => onCiteClick?.({ page: risk.page, section: risk.section, claim_text: risk.quoted_text })}
                >
                  📄 Page {risk.page} {risk.section ? `(§ ${risk.section})` : ""}
                </button>
              )}
            </div>
            
            <div className="risk-recommendation">
              <strong>💡 Recommendation:</strong> {risk.recommendation}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
