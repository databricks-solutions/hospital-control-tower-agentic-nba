"""Pre-agent orchestrator for ChatGPT-style tool selection."""
import os
from typing import List, Dict, Any, Optional
from .tools import execute_sql, search_encounters, write_analysis

CATALOG = os.environ.get("CATALOG", "")
SCHEMA = os.environ.get("SCHEMA", "med_logistics_nba")


def classify_intent(message: str) -> str:
    message_lower = message.lower()
    query_keywords = ["how many", "count", "list", "show", "get", "which",
                     "what is the", "average", "total", "sum", "max", "min"]
    if any(kw in message_lower for kw in query_keywords):
        return "query"
    search_keywords = ["find", "search", "similar", "like", "related", "about", "describe", "explain"]
    if any(kw in message_lower for kw in search_keywords):
        return "search"
    analyze_keywords = ["analyze", "analysis", "report", "insight", "recommend", "trend", "pattern",
                       "optimize", "compare", "why", "reduce", "lower", "next best action", "nba",
                       "sop", "procedure", "protocol"]
    if any(kw in message_lower for kw in analyze_keywords):
        return "analyze"
    return "general"


def select_tools_for_context(message: str, user_context: Optional[Dict[str, Any]] = None) -> List:
    intent = classify_intent(message)
    if intent == "query":
        return [execute_sql]
    elif intent == "search":
        return [search_encounters]
    elif intent == "analyze":
        return [execute_sql, search_encounters, write_analysis]
    else:
        return [execute_sql, search_encounters]


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
    return base_prompt
