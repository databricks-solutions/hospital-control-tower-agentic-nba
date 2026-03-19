"""Multi-agent deep analysis graph + quick query via LangGraph."""
import os
import logging
from typing import Dict, List, Optional, Annotated
from operator import add

from databricks_langchain import ChatDatabricks
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from .tools import (
    ORCHESTRATOR_TOOLS,
    execute_sql, search_encounters, write_analysis,
    ANALYSIS_TABLE, WAREHOUSE_ID,
)
from .orchestrator import select_tools_for_context, get_system_prompt_for_context

logger = logging.getLogger(__name__)

LLM_ORCHESTRATOR = os.environ.get("LLM_MODEL_ORCHESTRATOR", "databricks-gpt-oss-120b")
LLM_RAG = os.environ.get("LLM_MODEL_RAG", "databricks-claude-sonnet-4-5")
CATALOG = os.environ.get("CATALOG", "")
SCHEMA = os.environ.get("SCHEMA", "med_logistics_nba")

ANALYSIS_TYPES = ["cost_monitoring", "los_analysis", "ed_performance", "staffing_analysis", "compliance_monitoring"]


def get_llm():
    return ChatDatabricks(endpoint=LLM_RAG)


def _execute_query(sql: str) -> dict:
    """Internal SQL execution for prerequisite checks."""
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        result = w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="30s",
        )
        if result.status.state.value == "SUCCEEDED":
            if result.result and result.result.data_array:
                columns = [col.name for col in result.manifest.schema.columns]
                rows = [dict(zip(columns, row)) for row in result.result.data_array]
                return {"data": rows, "success": True}
            return {"data": [], "success": True}
        return {"error": str(result.status.error)}
    except Exception as e:
        return {"error": str(e)}


def check_prerequisite_analyses() -> str:
    """Query analysis_outputs for recent analyses (last 24h) by type."""
    try:
        sql = f"""
        SELECT analysis_type, MAX(created_at) AS last_run
        FROM {ANALYSIS_TABLE}
        WHERE created_at >= current_timestamp() - INTERVAL 24 HOURS
        GROUP BY analysis_type
        """
        result = _execute_query(sql)
        if result.get("error"):
            return "Unable to check prerequisites (query error)."
        rows = result.get("data", [])
        found = {r["analysis_type"]: r["last_run"] for r in rows}
        lines = []
        for atype in ANALYSIS_TYPES:
            if atype in found:
                lines.append(f"  {atype}: available (last run: {found[atype]})")
            else:
                lines.append(f"  {atype}: MISSING -- no analysis in last 24h")
        return "Prerequisite analysis status (last 24h):\n" + "\n".join(lines)
    except Exception as e:
        logger.error(f"check_prerequisite_analyses error: {e}")
        return f"Unable to check prerequisites: {e}"


# ===========================================================================
# Quick query
# ===========================================================================

def create_orchestrator_agent(message: str, user_context: Optional[Dict] = None):
    tools = select_tools_for_context(message, user_context)
    system_prompt = get_system_prompt_for_context(message, tools, user_context)
    llm = ChatDatabricks(endpoint=LLM_ORCHESTRATOR)
    agent = create_react_agent(llm, tools if tools else ORCHESTRATOR_TOOLS)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=message)]
    result = agent.invoke({"messages": messages})
    response_content = ""
    tool_calls_made = []
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage):
            if msg.content:
                response_content = msg.content
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                tool_calls_made.extend([tc.get("name", "unknown") for tc in msg.tool_calls])
    return {"response": response_content, "tool_calls": list(set(tool_calls_made)), "mode": "orchestrator"}


# ===========================================================================
# Multi-agent deep analysis
# ===========================================================================

class DeepAnalysisState(TypedDict):
    messages: Annotated[list, add]
    user_query: str
    plan: str
    retrieved_evidence: str
    prerequisite_status: str
    analysis_result: str
    needs_clarification: bool
    clarification_question: str
    next_step: str
    iteration: Annotated[list, add]
    tool_calls_made: Annotated[list, add]


SUPERVISOR_PROMPT = """You are a supervisor coordinating a deep analysis of hospital operations data.

Given the user's question and the current analysis state, decide the single next step.
Respond with EXACTLY one word from: CLARIFY, PLAN, RETRIEVE, ANALYZE, RESPOND.

Decision rules:
- CLARIFY  -- if the user question is too vague to act on
- PLAN     -- if no plan exists yet
- RETRIEVE -- if a plan exists but evidence has not been gathered
- ANALYZE  -- if evidence has been gathered and is ready for interpretation
- RESPOND  -- if the analysis is complete OR you need to deliver a clarification

Current state will be provided. Return ONLY one word."""


PLANNER_PROMPT = f"""You are a planning specialist for hospital operations analysis.

Given the user question and prerequisite analysis status, produce a concise numbered plan
of data-gathering steps the Retrieval agent should execute.

Available tables in {CATALOG}.{SCHEMA}:
- dim_encounters, fact_drug_costs, fact_staffing, fact_ed_wait_times, fact_operational_kpis, hospital_overview

Available tools: execute_sql, search_encounters

IMPORTANT: If the prerequisite status shows a relevant analysis is MISSING, note it.
Keep the plan to 3-6 steps max. Return a numbered list."""


RETRIEVAL_PROMPT = f"""You are a data retrieval specialist for hospital operations.

Execute the data-gathering plan provided. For EACH piece of data, note which tool provided it.

Format:
### Source: [tool_name]
[data / result summary]

Use {CATALOG}.{SCHEMA} as the catalog/schema for SQL queries."""


ANALYST_PROMPT = """You are a senior hospital operations analyst.

Given the retrieved evidence, produce a structured analysis:

## Evidence Summary
Brief list of data sources used.

## Key Findings
Numbered findings with inline source citations.

## Recommendations
For each: Action, Evidence, Expected Impact, Priority (High/Medium/Low).

## Prerequisites Needed
If any prerequisite analyses are missing, state: "Consider running [type] for a more complete picture."

Be concise. Lead with the most impactful recommendation.
Use write_analysis to save key findings."""


def supervisor_node(state: DeepAnalysisState) -> dict:
    """LLM-based router that decides the next step."""
    llm = get_llm()
    context_parts = [f"User question: {state['user_query']}"]
    if state.get("plan"):
        context_parts.append(f"Plan exists: yes ({state['plan'][:200]}...)")
    else:
        context_parts.append("Plan exists: no")
    context_parts.append("Evidence: gathered" if state.get("retrieved_evidence") else "Evidence: not yet gathered")
    context_parts.append("Analysis: complete" if state.get("analysis_result") else "Analysis: not complete")

    resp = llm.invoke([SystemMessage(content=SUPERVISOR_PROMPT), HumanMessage(content="\n".join(context_parts))])
    decision = resp.content.strip().upper().split()[0] if resp.content else "RESPOND"
    valid = {"CLARIFY", "PLAN", "RETRIEVE", "ANALYZE", "RESPOND"}
    if decision not in valid:
        decision = "RESPOND"

    if len(state.get("iteration", [])) >= 3:
        if state.get("analysis_result"):
            decision = "RESPOND"
        elif state.get("retrieved_evidence"):
            decision = "ANALYZE"
        else:
            decision = "RESPOND"

    return {"next_step": decision, "iteration": [1]}


def planner_node(state: DeepAnalysisState) -> dict:
    llm = get_llm()
    context = f"User question: {state['user_query']}\n\n{state.get('prerequisite_status', 'Prerequisite status unknown.')}"
    resp = llm.invoke([SystemMessage(content=PLANNER_PROMPT), HumanMessage(content=context)])
    return {"plan": resp.content, "messages": []}


def retrieval_node(state: DeepAnalysisState) -> dict:
    llm = get_llm()
    agent = create_react_agent(llm, [execute_sql, search_encounters])
    prompt = f"Execute this data-gathering plan:\n\n{state.get('plan', '')}\n\nUser question: {state['user_query']}"
    result = agent.invoke({"messages": [SystemMessage(content=RETRIEVAL_PROMPT), HumanMessage(content=prompt)]})
    evidence = ""
    tools_used = []
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage):
            if msg.content:
                evidence = msg.content
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                tools_used.extend([tc.get("name", "unknown") for tc in msg.tool_calls])
    return {"retrieved_evidence": evidence, "tool_calls_made": tools_used, "messages": []}


def analyst_node(state: DeepAnalysisState) -> dict:
    llm = get_llm()
    agent = create_react_agent(llm, [write_analysis])
    context = (
        f"User question: {state['user_query']}\n\n"
        f"Plan:\n{state.get('plan', 'N/A')}\n\n"
        f"Retrieved Evidence:\n{state.get('retrieved_evidence', 'N/A')}\n\n"
        f"{state.get('prerequisite_status', '')}"
    )
    result = agent.invoke({"messages": [SystemMessage(content=ANALYST_PROMPT), HumanMessage(content=context)]})
    analysis = ""
    tools_used = []
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage):
            if msg.content:
                analysis = msg.content
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                tools_used.extend([tc.get("name", "unknown") for tc in msg.tool_calls])
    return {"analysis_result": analysis, "tool_calls_made": tools_used, "messages": []}


def respond_node(state: DeepAnalysisState) -> dict:
    if state.get("needs_clarification"):
        return {"messages": [AIMessage(content=state.get("clarification_question", "Could you clarify your question?"))]}
    if state.get("analysis_result"):
        return {"messages": [AIMessage(content=state["analysis_result"])]}
    llm = get_llm()
    resp = llm.invoke([
        SystemMessage(content="Summarize what you know so far and explain that a complete analysis could not be finished."),
        HumanMessage(content=f"Question: {state['user_query']}\nEvidence: {state.get('retrieved_evidence', 'none')}"),
    ])
    return {"messages": [AIMessage(content=resp.content)]}


def clarify_node(state: DeepAnalysisState) -> dict:
    llm = get_llm()
    resp = llm.invoke([
        SystemMessage(content="The user's question is ambiguous. Ask a brief, specific clarifying question."),
        HumanMessage(content=f"User question: {state['user_query']}"),
    ])
    return {"needs_clarification": True, "clarification_question": resp.content, "next_step": "RESPOND", "messages": []}


def route_supervisor(state: DeepAnalysisState) -> str:
    return {"CLARIFY": "clarify", "PLAN": "planner", "RETRIEVE": "retrieval",
            "ANALYZE": "analyst", "RESPOND": "respond"}.get(state.get("next_step", "RESPOND"), "respond")


def build_deep_graph():
    graph = StateGraph(DeepAnalysisState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("planner", planner_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("respond", respond_node)
    graph.add_node("clarify", clarify_node)
    graph.set_entry_point("supervisor")
    graph.add_conditional_edges("supervisor", route_supervisor)
    graph.add_edge("planner", "supervisor")
    graph.add_edge("retrieval", "supervisor")
    graph.add_edge("analyst", "supervisor")
    graph.add_edge("clarify", "respond")
    graph.add_edge("respond", END)
    return graph.compile()


_deep_graph = None


def get_deep_graph():
    global _deep_graph
    if _deep_graph is None:
        _deep_graph = build_deep_graph()
    return _deep_graph


# ===========================================================================
# Public API
# ===========================================================================

def invoke_rag_agent(message: str, history: Optional[List[Dict]] = None) -> Dict:
    try:
        graph = get_deep_graph()
        prereq_status = check_prerequisite_analyses()

        query = message
        if history:
            context_lines = []
            for msg in history[-6:]:
                role = msg.get("role", "user")
                context_lines.append(f"{role}: {msg['content']}")
            context_lines.append(f"user: {message}")
            query = "Conversation so far:\n" + "\n".join(context_lines) + "\n\nRespond to the latest user message."

        initial_state = {
            "messages": [], "user_query": query, "plan": "", "retrieved_evidence": "",
            "prerequisite_status": prereq_status, "analysis_result": "",
            "needs_clarification": False, "clarification_question": "",
            "next_step": "", "iteration": [], "tool_calls_made": [],
        }
        result = graph.invoke(initial_state)
        response_content = ""
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                response_content = msg.content
                break
        if not response_content:
            response_content = result.get("analysis_result", "Analysis complete but no output was generated.")
        tool_calls = list(set(result.get("tool_calls_made", [])))
        return {"response": response_content, "tool_calls": tool_calls, "mode": "rag"}
    except Exception as e:
        logger.error(f"Deep analysis error: {e}", exc_info=True)
        return {"response": f"Error: {str(e)}", "tool_calls": [], "mode": "rag", "error": str(e)}


def invoke_agent(message: str, mode: str = "orchestrator", history: Optional[List[Dict]] = None,
                 user_context: Optional[Dict] = None) -> Dict:
    if mode == "orchestrator":
        return create_orchestrator_agent(message, user_context)
    else:
        return invoke_rag_agent(message, history)
