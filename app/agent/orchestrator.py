"""Pre-agent orchestrator for LLM-based tool selection."""
import logging
from enum import Enum
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field

from .config import CATALOG, SCHEMA, LLM_ORCHESTRATOR
from .tools import execute_sql, search_encounters, search_sops, write_analysis

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    sop = "sop"
    analyze = "analyze"
    query = "query"
    search = "search"
    general = "general"


class IntentClassification(BaseModel):
    intent: Intent = Field(description="The classified intent of the user message")


_INTENT_TOOLS = {
    Intent.sop: [execute_sql, search_sops, search_encounters],
    Intent.analyze: [execute_sql, search_encounters, search_sops, write_analysis],
    Intent.query: [execute_sql, search_sops],
    Intent.search: [search_encounters, search_sops],
    Intent.general: [execute_sql, search_encounters, search_sops],
}

_classifier_llm = None


def _get_classifier():
    global _classifier_llm
    if _classifier_llm is None:
        from databricks_langchain import ChatDatabricks
        _classifier_llm = ChatDatabricks(
            endpoint=LLM_ORCHESTRATOR, temperature=0
        ).with_structured_output(IntentClassification)
    return _classifier_llm


_CLASSIFY_SYSTEM = (
    "Classify the user message into one intent.\n"
    "- sop: questions about procedures, policies, guidelines, compliance, thresholds, or regulatory rules\n"
    "- analyze: requests for analysis, reports, root-cause investigation, recommendations, trends\n"
    "- query: factual data lookups (counts, averages, totals, lists)\n"
    "- search: semantic similarity searches for encounters or documents\n"
    "- general: anything else\n"
    "Return only the intent."
)


def classify_intent(message: str) -> str:
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        result = _get_classifier().invoke([
            SystemMessage(content=_CLASSIFY_SYSTEM),
            HumanMessage(content=message),
        ])
        return result.intent.value
    except Exception as e:
        logger.warning(f"LLM intent classification failed, falling back to keyword: {e}")
        return _keyword_fallback(message)


def _keyword_fallback(message: str) -> str:
    """Fallback keyword matcher used when the LLM classifier is unavailable."""
    ml = message.lower()
    sop_kw = ["sop", "procedure", "protocol", "policy", "guideline", "compliance", "threshold", "regulatory"]
    if any(kw in ml for kw in sop_kw):
        return "sop"
    if any(kw in ml for kw in ["analyze", "report", "recommend", "trend", "why", "root cause", "nba"]):
        return "analyze"
    if any(kw in ml for kw in ["how many", "count", "list", "show", "average", "total"]):
        return "query"
    if any(kw in ml for kw in ["find", "search", "similar"]):
        return "search"
    return "general"


def select_tools_for_context(message: str, user_context: Optional[Dict[str, Any]] = None) -> tuple:
    """Returns (tools_list, intent_string)."""
    intent = classify_intent(message)
    tools = _INTENT_TOOLS.get(Intent(intent), _INTENT_TOOLS[Intent.general])
    return tools, intent


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
