"""Pre-agent orchestrator for ChatGPT-style tool selection."""
from typing import List, Dict, Any, Optional
from .config import CATALOG, SCHEMA
from .tools import execute_sql, search_fund_documents, search_investment_policies, write_analysis


POLICY_KEYWORDS = [
    "policy", "policies", "ips", "guideline", "compliance", "limit", "threshold",
    "allowed", "permitted", "prohibited", "restriction", "rule", "procedure",
    "protocol", "governance", "mandate", "target allocation", "rebalance",
    "watchlist criteria", "due diligence", "esg", "responsible invest",
    "valuation standard", "capital call", "distribution waterfall",
    "liquidity requirement", "concentration limit", "benchmark",
    "underperformance", "escalation", "risk framework", "reporting requirement",
    "what should", "what does the ips say", "what are the rules",
    "according to", "per our policy", "what is our",
]


def classify_intent(message: str) -> str:
    message_lower = message.lower()
    if any(kw in message_lower for kw in POLICY_KEYWORDS):
        return "policy"
    analyze_keywords = ["analyze", "analysis", "report", "insight", "recommend", "trend", "pattern",
                       "optimize", "compare", "why", "reduce", "performance", "allocation",
                       "concentration", "exposure", "risk", "return", "outlook", "objective",
                       "prospect", "assess", "evaluate", "review", "deep dive", "investigate"]
    if any(kw in message_lower for kw in analyze_keywords):
        return "analyze"
    query_keywords = ["how many", "count", "list", "show", "get", "which",
                     "what is the", "average", "total", "sum", "max", "min"]
    if any(kw in message_lower for kw in query_keywords):
        return "query"
    search_keywords = ["find", "search", "similar", "like", "related", "about", "describe", "explain"]
    if any(kw in message_lower for kw in search_keywords):
        return "search"
    return "general"


def select_tools_for_context(message: str, user_context: Optional[Dict[str, Any]] = None) -> tuple:
    """Returns (tools_list, intent_string)."""
    intent = classify_intent(message)
    if intent == "policy":
        return [execute_sql, search_investment_policies, search_fund_documents], intent
    elif intent == "analyze":
        return [execute_sql, search_fund_documents, search_investment_policies, write_analysis], intent
    elif intent == "query":
        return [execute_sql, search_investment_policies], intent
    elif intent == "search":
        return [search_fund_documents, search_investment_policies], intent
    else:
        return [execute_sql, search_fund_documents, search_investment_policies], intent


def get_system_prompt_for_context(message: str, tools: List, user_context: Optional[Dict[str, Any]] = None) -> str:
    tool_names = [t.name for t in tools]
    base_prompt = f"""You are an investment portfolio intelligence assistant in Quick Query mode.

BEHAVIOR:
- Be concise. Return the requested data with a 1-2 sentence interpretation.
- Do NOT perform multi-step deep analysis. If the question requires root-cause analysis,
  impact assessment, or a comprehensive investment report, say: "This question would benefit from
  Deep Analysis mode, which can run a full investigation with evidence sourcing and
  impact assessment. Switch to Deep Analysis mode for a comprehensive answer."
- For simple factual questions, answer directly with data.

Available data in {CATALOG}.{SCHEMA}:
- dim_funds: Fund dimension (manager, strategy, AUM, status, vintage)
- fact_fund_performance: Monthly returns, NAV, alpha, benchmark comparison
- fact_portfolio_holdings: Position-level holdings by sector, geography
- fact_fund_flows: Capital calls, distributions, liquidity terms
- fact_portfolio_kpis: Portfolio-level KPIs by strategy segment
- portfolio_overview: Summary VIEW
"""
    if "execute_sql" in tool_names:
        base_prompt += f"\nWhen writing SQL, use catalog/schema: {CATALOG}.{SCHEMA}\n"
    if "search_investment_policies" in tool_names:
        base_prompt += """
POLICY GROUNDING (important):
You have access to the firm's Investment Policy Statement (IPS) and related governance documents
via search_investment_policies. Use this tool proactively when:
- Any question touches on targets, limits, thresholds, or allocation guidelines
- Questions about what is allowed, required, or recommended
- Providing recommendations that should reference firm policy
- Questions about outlook, objectives, due diligence, ESG, risk, or compliance
When you cite policy, quote the specific section (e.g., "Per IPS Section 3.1, single GP exposure maximum is 8% of NAV").
"""
    return base_prompt
