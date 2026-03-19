"""Pre-agent orchestrator for ChatGPT-style tool selection."""
from typing import List, Dict, Any, Optional
from .config import CATALOG, SCHEMA
from .tools import execute_sql, search_encounters, search_sops, write_analysis


SOP_KEYWORDS = [
    "sop", "procedure", "protocol", "policy", "guideline", "compliance",
    "threshold", "limit", "allowed", "permitted", "restriction", "rule",
    "governance", "accreditation", "regulatory", "jcaho", "cms",
    "what should", "what does the sop say", "what are the rules",
    "according to", "per our policy", "what is our",
    "escalation", "staffing ratio", "nurse ratio", "bed capacity",
    "discharge planning", "readmission prevention", "triage protocol",
    "formulary", "antibiotic stewardship", "hand hygiene",
]


def classify_intent(message: str) -> str:
    message_lower = message.lower()
    if any(kw in message_lower for kw in SOP_KEYWORDS):
        return "sop"
    analyze_keywords = ["analyze", "analysis", "report", "insight", "recommend", "trend", "pattern",
                       "optimize", "compare", "why", "reduce", "lower", "next best action", "nba",
                       "root cause", "investigate", "deep dive", "assess", "evaluate", "review"]
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
    if intent == "sop":
        return [execute_sql, search_sops, search_encounters], intent
    elif intent == "analyze":
        return [execute_sql, search_encounters, search_sops, write_analysis], intent
    elif intent == "query":
        return [execute_sql, search_sops], intent
    elif intent == "search":
        return [search_encounters, search_sops], intent
    else:
        return [execute_sql, search_encounters, search_sops], intent


def get_system_prompt_for_context(message: str, tools: List, user_context: Optional[Dict[str, Any]] = None) -> str:
    tool_names = [t.name for t in tools]
    base_prompt = f"""You are a medical logistics operations assistant in Quick Query mode.

BEHAVIOR:
- Be concise. Return the requested data with a 1-2 sentence interpretation.
- Do NOT perform multi-step deep analysis. If the question requires root-cause analysis,
  impact assessment, or a Next Best Action report, say: "This question would benefit from
  Deep Analysis mode, which can run a full investigation with evidence sourcing and
  impact assessment. Switch to Deep Analysis mode for a comprehensive answer."
- For simple factual questions, answer directly with data.

Available data in {CATALOG}.{SCHEMA}:
- dim_encounters: Patient encounters (hospital, department, LOS, discharge day, payer, readmission)
- fact_drug_costs: Drug costs by encounter, drug, category
- fact_staffing: Staffing levels by type (full_time, contract, per_diem)
- fact_ed_wait_times: ED visit metrics by acuity level
- fact_operational_kpis: Daily KPIs per hospital/department
- hospital_overview: Summary VIEW
"""
    if "execute_sql" in tool_names:
        base_prompt += f"\nWhen writing SQL, use catalog/schema: {CATALOG}.{SCHEMA}\n"
    if "search_sops" in tool_names:
        base_prompt += """
SOP GROUNDING (important):
You have access to the hospital's Standard Operating Procedures via search_sops. Use this tool proactively when:
- Any question touches on targets, thresholds, or operational guidelines
- Questions about what is required, recommended, or mandated
- Providing recommendations that should reference hospital policy
- Questions about staffing ratios, discharge protocols, ED triage, or compliance
When you cite an SOP, quote the specific section or procedure name.
"""
    return base_prompt
