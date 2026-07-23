"""Pre-agent orchestrator for LLM-based tool selection.

NOTE: Notebook-accessible copy. Authoritative version is app/agent/orchestrator.py.
"""
import os
import logging
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from .tools import execute_sql, search_encounters, write_analysis

logger = logging.getLogger(__name__)

CATALOG = os.environ.get("CATALOG", "")
SCHEMA = os.environ.get("SCHEMA", "med_logistics_nba")
LLM_ORCHESTRATOR = os.environ.get("LLM_MODEL_ORCHESTRATOR", "databricks-meta-llama-3-3-70b-instruct")


class Intent(str, Enum):
    sop = "sop"
    analyze = "analyze"
    query = "query"
    search = "search"
    general = "general"


class IntentClassification(BaseModel):
    intent: Intent = Field(description="The classified intent of the user message")


_INTENT_TOOLS = {
    Intent.sop: [execute_sql, search_encounters],
    Intent.analyze: [execute_sql, search_encounters, write_analysis],
    Intent.query: [execute_sql],
    Intent.search: [search_encounters],
    Intent.general: [execute_sql, search_encounters],
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
    "- sop: procedures, policies, guidelines, compliance\n"
    "- analyze: analysis, reports, root-cause investigation\n"
    "- query: factual data lookups (counts, averages, totals)\n"
    "- search: semantic similarity searches\n"
    "- general: anything else\n"
    "Return only the intent."
)


def classify_intent(message):
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        result = _get_classifier().invoke([
            SystemMessage(content=_CLASSIFY_SYSTEM),
            HumanMessage(content=message),
        ])
        return result.intent.value
    except Exception as e:
        logger.warning("LLM intent classification failed: %s", e)
        return _keyword_fallback(message)


def _keyword_fallback(message):
    ml = message.lower()
    if any(kw in ml for kw in ["sop", "procedure", "protocol", "policy", "compliance"]):
        return "sop"
    if any(kw in ml for kw in ["analyze", "report", "recommend", "trend", "why", "root cause"]):
        return "analyze"
    if any(kw in ml for kw in ["how many", "count", "list", "show", "average", "total"]):
        return "query"
    if any(kw in ml for kw in ["find", "search", "similar"]):
        return "search"
    return "general"


def select_tools_for_context(message, user_context=None):
    """Returns (tools_list, intent_string)."""
    intent = classify_intent(message)
    tools = _INTENT_TOOLS.get(Intent(intent), _INTENT_TOOLS[Intent.general])
    return tools, intent


def get_system_prompt_for_context(message, tools, user_context=None):
    tool_names = [t.name for t in tools]
    base = (
        "You are a medical logistics operations assistant in Quick Query mode.\n\n"
        "Be concise. Answer directly with data.\n\n"
    )
    base += "Available data in " + CATALOG + "." + SCHEMA + ":\n"
    base += "- dim_encounters, fact_drug_costs, fact_staffing, fact_ed_wait_times, fact_operational_kpis\n"
    if "execute_sql" in tool_names:
        base += "\nWhen writing SQL, use catalog/schema: " + CATALOG + "." + SCHEMA + "\n"
    return base
