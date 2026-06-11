"""JSON schemas and system prompts for risk report generation."""

RISK_SYSTEM_PROMPT = (
    "You are a senior legal counsel performing a rigorous risk assessment of the attached contract. "
    "Analyze the document thoroughly and categorize risks by severity based on financial exposure and legal enforceability. "
    "Focus on categories like Liability Limit, Termination, IP Ownership, Indemnification, Payment Terms, Confidentiality, Data Privacy, Force Majeure, Governing Law, and Non-Compete. "
    "For every risk identified, you MUST cite the exact verbatim text and page number from the contract. "
    "Provide actionable recommendations for renegotiation. "
    "If a standard protective clause is missing (e.g., 'No force majeure clause found'), flag it as a risk. "
    "Return the exact JSON structure requested."
)

RISK_REPORT_SCHEMA = {
    "type": "object",
    "required": ["overall_risk_score", "summary", "risks"],
    "properties": {
        "overall_risk_score": {
            "type": "string", 
            "enum": ["high", "medium", "low"],
            "description": "The overall risk score for the contract"
        },
        "summary": {
            "type": "string", 
            "description": "Executive summary of the contract's overall risk posture."
        },
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["category", "severity", "risk_description", "quoted_text", "page", "recommendation"],
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "The category of the risk (e.g., Liability Limit, Termination, etc.)"
                    },
                    "severity": {
                        "type": "string", 
                        "enum": ["high", "medium", "low"]
                    },
                    "clause_name": {
                        "type": "string", 
                        "description": "Name of the clause or section heading."
                    },
                    "risk_description": {
                        "type": "string", 
                        "description": "Why this clause poses a risk to our organization."
                    },
                    "quoted_text": {
                        "type": "string", 
                        "description": "Verbatim quote from the contract confirming the risk."
                    },
                    "page": {
                        "type": "integer"
                    },
                    "section": {
                        "type": "string"
                    },
                    "recommendation": {
                        "type": "string", 
                        "description": "Actionable advice on how to renegotiate or remediate this risk."
                    }
                }
            }
        }
    }
}
