"""Multi-agent deep analysis graph + quick query via LangGraph."""
import logging
import queue
import threading
from typing import Dict, List, Optional, Annotated
from operator import add

from databricks_langchain import ChatDatabricks
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from .config import (
    CATALOG, SCHEMA, LLM_MODEL, MLFLOW_EXPERIMENT,
    ANALYSIS_TABLE, MAX_SUPERVISOR_ITERATIONS,
)
from .tools import (
    QUICK_TOOLS,
    execute_sql, search_fund_documents, search_investment_policies,
    analyze_performance_drivers, analyze_concentration,
    check_fund_flows, check_exposure_shifts,
    check_portfolio_kpis, check_data_freshness,
    write_analysis, _execute_query,
)
from .orchestrator import select_tools_for_context, get_system_prompt_for_context

logger = logging.getLogger(__name__)

MLFLOW_ENABLED = False
MLFLOW_EXPERIMENT_ID = None
try:
    import mlflow
    mlflow.set_tracking_uri("databricks")
    exp = mlflow.set_experiment(MLFLOW_EXPERIMENT)
    MLFLOW_EXPERIMENT_ID = exp.experiment_id
    mlflow.langchain.autolog(silent=True)
    trace = mlflow.trace
    MLFLOW_ENABLED = True
    logger.info(f"MLflow tracing enabled, experiment: {MLFLOW_EXPERIMENT} (id={MLFLOW_EXPERIMENT_ID})")
except Exception as e:
    logger.warning(f"MLflow tracing not available: {e}")
    def trace(**kwargs):
        """No-op decorator when mlflow is unavailable."""
        return lambda fn: fn

try:
    import litellm
    litellm.suppress_debug_info = True
except ImportError:
    pass
for _name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy", "litellm"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)

ANALYSIS_TYPES = ["performance_monitoring", "concentration_analysis", "flow_analysis", "exposure_analysis", "policy_compliance"]

_local = threading.local()


def _emit_progress(stage: str, message: str, agent: str = ""):
    trace = getattr(_local, "routing_trace", None)
    if agent and trace is not None:
        trace.append({"agent": agent, "action": stage, "message": message})
    q = getattr(_local, "progress_queue", None)
    if q is not None:
        q.put({"stage": stage, "message": message})


_cached_llm = None

def get_llm():
    global _cached_llm
    if _cached_llm is None:
        _cached_llm = ChatDatabricks(endpoint=LLM_MODEL)
    return _cached_llm


# ---------------------------------------------------------------------------
# Prerequisite analysis check
# ---------------------------------------------------------------------------

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
        if result.get("error") or not result.get("success", False):
            return "Unable to check prerequisites (query error)."
        rows = result.get("rows", [])
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

@trace(name="quick_query", span_type="CHAIN")
def create_quick_response(message: str, user_context: Optional[Dict] = None) -> Dict:
    selected_tools, intent = select_tools_for_context(message, user_context)
    system_prompt = get_system_prompt_for_context(message, selected_tools, user_context)
    if not selected_tools:
        selected_tools = QUICK_TOOLS[:2]
    try:
        llm = get_llm()
        agent = create_react_agent(llm, selected_tools)
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
        return {"response": response_content, "tool_calls": list(set(tool_calls_made)), "mode": "quick", "intent": intent}
    except Exception as e:
        logger.error(f"Quick query error: {e}", exc_info=True)
        try:
            llm = get_llm()
            resp = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=message),
            ])
            return {"response": resp.content, "tool_calls": [], "mode": "quick", "fallback": True, "intent": intent}
        except Exception:
            return {"response": f"Error: {str(e)}", "tool_calls": [], "mode": "quick", "error": str(e), "intent": intent}


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


# ---- Sub-agent system prompts ----

SUPERVISOR_PROMPT = """You are a supervisor coordinating a deep analysis of investment portfolio data.

Given the user's question and the current analysis state, decide the single next step.
Respond with EXACTLY one word from: CLARIFY, PLAN, RETRIEVE, ANALYZE, RESPOND.

Decision rules:
- CLARIFY  -- if the user question is too vague to act on (e.g. "help me" with no topic)
- PLAN     -- if no plan exists yet
- RETRIEVE -- if a plan exists but evidence has not been gathered
- ANALYZE  -- if evidence has been gathered and is ready for interpretation
- RESPOND  -- if the analysis is complete OR you need to deliver a clarification

Current state will be provided. Return ONLY one word."""


PLANNER_PROMPT = f"""You are a planning specialist for investment portfolio analysis.

Given the user question and prerequisite analysis status, produce a concise numbered plan
of data-gathering steps the Retrieval agent should execute.

Available tables in {CATALOG}.{SCHEMA}:
- dim_funds (fund_id, fund_name, manager_name, strategy, vintage_year, aum, commitment, status, domicile, inception_date)
- fact_fund_performance (fund_id, date, nav, monthly_return, ytd_return, itd_return, benchmark_return, alpha)
- fact_portfolio_holdings (fund_id, date, position_name, sector, geography, pct_nav, market_value, change_from_prior)
- fact_fund_flows (fund_id, date, capital_calls, distributions, net_flow, commitment_remaining, liquidity_terms)
- fact_portfolio_kpis (date, portfolio_segment, total_aum, weighted_avg_return, concentration_top5_pct, benchmark_spread, manager_count)
- portfolio_overview

Available tools the Retrieval agent can call:
- execute_sql, search_fund_documents, search_investment_policies, analyze_performance_drivers, analyze_concentration,
  check_fund_flows, check_exposure_shifts, check_portfolio_kpis, check_data_freshness

IMPORTANT:
- If the prerequisite status shows a relevant analysis is MISSING, include a note:
  "NOTE: [analysis_type] has not been run recently. The user should run this analysis first,
  or the Retrieval agent should gather the raw data directly."
- Focus on what data is needed and which tools to use. Be specific about SQL queries.
- Keep the plan to 3-6 steps max.
- ALWAYS include a step to search_investment_policies for the relevant policy context
  (thresholds, guidelines, procedures) so the Analyst can ground recommendations in firm policy.

Return the plan as a numbered list."""


RETRIEVAL_PROMPT = f"""You are a data retrieval specialist for investment portfolio analysis.

Execute the data-gathering plan provided. For EACH piece of data you retrieve, note which
tool provided it so the Analyst can cite sources.

Format your output as:
### Source: [tool_name]
[data / result summary]

Gather all evidence requested in the plan. Be thorough but efficient.
Use {CATALOG}.{SCHEMA} as the catalog/schema for SQL queries."""


ANALYST_PROMPT = """You are a senior investment analyst. You interpret data and produce
actionable recommendations.

Given the retrieved evidence, produce a structured analysis with these sections:

## Evidence Summary

Brief list of data sources used and what they showed.

## Key Findings

Numbered findings with inline source citations (e.g. "[Source: execute_sql]").

## Recommendations

For each recommendation use this format (with a blank line between each item):

- **Action**: What to do

- **Evidence**: Data supporting this (cite source)

- **Expected Impact**: Quantified where possible

- **IPS/Policy Reference**: ALWAYS cite the specific IPS section and threshold (e.g., "IPS Section 3.1: single GP max 8% NAV"). If no policy was retrieved, note "No applicable IPS provision found" so the team knows it was checked.

- **Priority**: High / Medium / Low

## Prerequisites Needed

If any prerequisite analyses are missing (per the prerequisite status), list them here and
state: "Consider running [analysis_type] for a more complete picture."

FORMATTING RULES (critical):
- Always use proper markdown with blank lines between sections and list items.
- Use numbered lists (1. 2. 3.) for findings and bullet lists (- ) for recommendations.
- Put a blank line before and after every heading, list, and paragraph.
- Be concise. Lead with the most impactful recommendation.
Use write_analysis to save key findings when the analysis is significant."""


# ---- Node functions ----

@trace(name="supervisor", span_type="CHAIN")
def supervisor_node(state: DeepAnalysisState) -> dict:
    """LLM-based router that decides the next step."""
    _emit_progress("routing", "Deciding next step...", agent="supervisor")
    try:
        llm = get_llm()

        context_parts = [f"User question: {state['user_query']}"]
        if state.get("plan"):
            context_parts.append(f"Plan exists: yes ({state['plan'][:200]}...)")
        else:
            context_parts.append("Plan exists: no")
        context_parts.append("Evidence: gathered" if state.get("retrieved_evidence") else "Evidence: not yet gathered")
        context_parts.append("Analysis: complete" if state.get("analysis_result") else "Analysis: not complete")

        resp = llm.invoke([
            SystemMessage(content=SUPERVISOR_PROMPT),
            HumanMessage(content="\n".join(context_parts)),
        ])

        decision = resp.content.strip().upper().split()[0] if resp.content else "RESPOND"
        valid = {"CLARIFY", "PLAN", "RETRIEVE", "ANALYZE", "RESPOND"}
        if decision not in valid:
            decision = "RESPOND"
    except Exception as e:
        logger.error(f"Supervisor LLM error: {e}")
        decision = "RESPOND"

    if len(state.get("iteration", [])) >= MAX_SUPERVISOR_ITERATIONS:
        if state.get("analysis_result"):
            decision = "RESPOND"
        elif state.get("retrieved_evidence"):
            decision = "ANALYZE"
        else:
            decision = "RESPOND"

    _emit_progress("routing", f"Next: {decision}", agent="supervisor")
    return {"next_step": decision, "iteration": [1]}


@trace(name="planner", span_type="CHAIN")
def planner_node(state: DeepAnalysisState) -> dict:
    _emit_progress("planning", "Creating analysis plan...", agent="planner")
    try:
        llm = get_llm()
        context = (
            f"User question: {state['user_query']}\n\n"
            f"{state.get('prerequisite_status', 'Prerequisite status unknown.')}"
        )
        resp = llm.invoke([
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=context),
        ])
        return {"plan": resp.content, "messages": []}
    except Exception as e:
        logger.error(f"Planner LLM error: {e}")
        return {"plan": f"1. Gather relevant data for: {state['user_query']}", "messages": []}


@trace(name="retrieval", span_type="RETRIEVER")
def retrieval_node(state: DeepAnalysisState) -> dict:
    _emit_progress("retrieving", "Gathering evidence from data sources...", agent="retrieval")
    try:
        retrieval_tools = [
            execute_sql, search_fund_documents, search_investment_policies,
            analyze_performance_drivers, analyze_concentration,
            check_fund_flows, check_exposure_shifts,
            check_portfolio_kpis, check_data_freshness,
        ]
        llm = get_llm()
        agent = create_react_agent(llm, retrieval_tools)

        prompt = f"Execute this data-gathering plan:\n\n{state.get('plan', '')}\n\nUser question: {state['user_query']}"
        result = agent.invoke({
            "messages": [SystemMessage(content=RETRIEVAL_PROMPT), HumanMessage(content=prompt)]
        })

        evidence = ""
        tools_used = []
        for msg in result.get("messages", []):
            if isinstance(msg, AIMessage):
                if msg.content:
                    evidence = msg.content
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    tools_used.extend([tc.get("name", "unknown") for tc in msg.tool_calls])

        return {"retrieved_evidence": evidence, "tool_calls_made": tools_used, "messages": []}
    except Exception as e:
        logger.error(f"Retrieval agent error: {e}")
        return {"retrieved_evidence": f"Error retrieving data: {e}", "tool_calls_made": [], "messages": []}


@trace(name="analyst", span_type="CHAIN")
def analyst_node(state: DeepAnalysisState) -> dict:
    _emit_progress("analyzing", "Interpreting results and forming recommendations...", agent="analyst")
    try:
        llm = get_llm()
        agent = create_react_agent(llm, [write_analysis])

        context = (
            f"User question: {state['user_query']}\n\n"
            f"Plan:\n{state.get('plan', 'N/A')}\n\n"
            f"Retrieved Evidence:\n{state.get('retrieved_evidence', 'N/A')}\n\n"
            f"{state.get('prerequisite_status', '')}"
        )
        result = agent.invoke({
            "messages": [SystemMessage(content=ANALYST_PROMPT), HumanMessage(content=context)]
        })

        analysis = ""
        tools_used = []
        for msg in result.get("messages", []):
            if isinstance(msg, AIMessage):
                if msg.content and len(msg.content) > len(analysis):
                    analysis = msg.content
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    tools_used.extend([tc.get("name", "unknown") for tc in msg.tool_calls])

        return {"analysis_result": analysis, "tool_calls_made": tools_used, "messages": []}
    except Exception as e:
        logger.error(f"Analyst agent error: {e}")
        return {"analysis_result": f"The analysis could not be completed due to a model error. Please try again.", "tool_calls_made": [], "messages": []}


@trace(name="respond", span_type="CHAIN")
def respond_node(state: DeepAnalysisState) -> dict:
    _emit_progress("responding", "Preparing final response...", agent="respond")
    if state.get("needs_clarification"):
        return {"messages": [AIMessage(content=state.get("clarification_question", "Could you clarify your question?"))]}

    if state.get("analysis_result"):
        return {"messages": [AIMessage(content=state["analysis_result"])]}

    try:
        llm = get_llm()
        resp = llm.invoke([
            SystemMessage(content="Summarize what you know so far and explain that a complete analysis could not be finished. Be helpful."),
            HumanMessage(content=f"Question: {state['user_query']}\nEvidence: {state.get('retrieved_evidence', 'none')}\nPlan: {state.get('plan', 'none')}"),
        ])
        return {"messages": [AIMessage(content=resp.content)]}
    except Exception as e:
        logger.error(f"Respond LLM error: {e}")
        return {"messages": [AIMessage(content="The AI model is temporarily unavailable. Please try again in a moment.")]}


@trace(name="clarify", span_type="CHAIN")
def clarify_node(state: DeepAnalysisState) -> dict:
    _emit_progress("clarifying", "Asking for clarification...", agent="clarify")
    try:
        llm = get_llm()
        resp = llm.invoke([
            SystemMessage(content="The user's question is ambiguous. Ask a brief, specific clarifying question to narrow it down."),
            HumanMessage(content=f"User question: {state['user_query']}"),
        ])
        return {
            "needs_clarification": True,
            "clarification_question": resp.content,
            "next_step": "RESPOND",
            "messages": [],
        }
    except Exception as e:
        logger.error(f"Clarify LLM error: {e}")
        return {
            "needs_clarification": True,
            "clarification_question": "Could you provide more details about what you'd like to analyze?",
            "next_step": "RESPOND",
            "messages": [],
        }


# ---- Routing ----

def route_supervisor(state: DeepAnalysisState) -> str:
    return {
        "CLARIFY": "clarify",
        "PLAN": "planner",
        "RETRIEVE": "retrieval",
        "ANALYZE": "analyst",
        "RESPOND": "respond",
    }.get(state.get("next_step", "RESPOND"), "respond")


# ---- Graph builder ----

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


def _build_query(message: str, history: Optional[List[Dict]] = None) -> str:
    if history:
        context_lines = []
        for msg in history[-6:]:
            role = msg.get("role", "user")
            context_lines.append(f"{role}: {msg['content']}")
        context_lines.append(f"user: {message}")
        return "Conversation so far:\n" + "\n".join(context_lines) + "\n\nRespond to the latest user message."
    return message


def _run_deep_graph(query: str, prereq_status: str) -> Dict:
    graph = get_deep_graph()
    initial_state = {
        "messages": [],
        "user_query": query,
        "plan": "",
        "retrieved_evidence": "",
        "prerequisite_status": prereq_status,
        "analysis_result": "",
        "needs_clarification": False,
        "clarification_question": "",
        "next_step": "",
        "iteration": [],
        "tool_calls_made": [],
    }
    result = graph.invoke(initial_state)

    response_content = ""
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage) and msg.content and len(msg.content) > len(response_content):
            response_content = msg.content
    if not response_content:
        response_content = result.get("analysis_result", "Analysis complete but no output was generated.")

    tool_calls = list(set(result.get("tool_calls_made", [])))
    return {"response": response_content, "tool_calls": tool_calls, "mode": "deep"}


# ===========================================================================
# Public API
# ===========================================================================

def invoke_deep_agent(message: str, history: Optional[List[Dict]] = None) -> Dict:
    """Non-streaming deep analysis -- used by autonomous mode."""
    try:
        prereq_status = check_prerequisite_analyses()
        query = _build_query(message, history)
        return _run_deep_graph(query, prereq_status)
    except Exception as e:
        logger.error(f"Deep analysis error: {e}", exc_info=True)
        return {"response": f"Error during deep analysis: {str(e)}", "tool_calls": [], "mode": "deep", "error": str(e)}


def invoke_deep_agent_streaming(message: str, history: Optional[List[Dict]] = None) -> queue.Queue:
    """Streaming deep analysis -- returns a Queue that yields progress events.

    Events:
        {"stage": "planning", "message": "..."}
        {"stage": "retrieving", "message": "..."}
        {"stage": "analyzing", "message": "..."}
        {"stage": "done", "response": "...", "tool_calls": [...]}
        {"stage": "error", "message": "..."}
    """
    q = queue.Queue()

    def _run():
        _local.progress_queue = q
        _local.routing_trace = []
        try:
            _emit_progress("starting", "Checking prerequisites...", agent="system")
            prereq_status = check_prerequisite_analyses()
            query = _build_query(message, history)
            result = _run_deep_graph(query, prereq_status)
            q.put({"stage": "done", "response": result["response"],
                   "tool_calls": result.get("tool_calls", []),
                   "routing_trace": list(_local.routing_trace)})
        except Exception as e:
            logger.error(f"Streaming deep analysis error: {e}", exc_info=True)
            q.put({"stage": "error", "message": str(e)})
        finally:
            _local.progress_queue = None
            _local.routing_trace = []

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return q


def invoke_agent(message: str, mode: str = "orchestrator", history: Optional[List[Dict]] = None,
                 user_context: Optional[Dict] = None) -> Dict:
    logger.info(f"Invoking agent: mode={mode}, message={message[:50]}...")
    if mode in ("orchestrator", "quick"):
        return create_quick_response(message, user_context)
    else:
        return invoke_deep_agent(message, history)


PLOT_SYSTEM_PROMPT = f"""You are a data visualization agent for an investment intelligence platform.

You will receive the text of an agent response about investment portfolio data.
Your job is to determine if the response contains data that can be plotted, and if so,
run a SQL query to get precise numbers and return a chart specification.

Available tables in {CATALOG}.{SCHEMA}:
- dim_funds: fund_id, fund_name, manager_name, strategy, vintage_year, aum, commitment, status, domicile, inception_date
- fact_fund_performance: fund_id, date, nav, monthly_return, ytd_return, itd_return, benchmark_return, alpha
- fact_portfolio_holdings: fund_id, date, position_name, sector, geography, pct_nav, market_value, change_from_prior
- fact_fund_flows: fund_id, date, capital_calls, distributions, net_flow, commitment_remaining, liquidity_terms
- fact_portfolio_kpis: date, portfolio_segment, total_aum, weighted_avg_return, concentration_top5_pct, benchmark_spread, manager_count
- portfolio_overview: strategy, fund_count, total_aum, avg_aum, manager_count, watchlist_count

Use the execute_sql tool to query the data, then return ONLY a JSON object (no markdown, no extra text) in this exact format:

If data IS suitable for plotting:
{{"type": "bar"|"line"|"pie"|"area", "title": "Chart Title", "data": [{{"name": "Label", "value": 123}}, ...], "xKey": "name", "yKeys": ["value"], "text": "Brief one-sentence caption"}}

For multi-series data use multiple yKeys:
{{"type": "bar", "title": "...", "data": [{{"name": "X", "series1": 10, "series2": 20}}, ...], "xKey": "name", "yKeys": ["series1", "series2"], "text": "..."}}

If data is NOT suitable for plotting:
{{"no_data": true, "reason": "Brief explanation why"}}

Rules:
- Always query the database for precise numbers -- do not invent data.
- Choose the chart type that best represents the data (bar for comparisons, line for time series, pie for proportions).
- Keep data arrays to 20 items or fewer. Aggregate if needed.
- Return ONLY the JSON object, nothing else."""


def create_plot_spec(content: str, history: Optional[List[Dict]] = None) -> Dict:
    """Use an LLM agent to extract a chart spec from an agent response."""
    try:
        llm = get_llm()
        agent = create_react_agent(llm, [execute_sql])
        context = f"Agent response to visualize:\n\n{content}"
        if history:
            recent = history[-4:]
            context = "Recent conversation:\n" + "\n".join(
                f"{m['role']}: {m['content'][:300]}" for m in recent
            ) + f"\n\nAgent response to visualize:\n\n{content}"

        result = agent.invoke({
            "messages": [SystemMessage(content=PLOT_SYSTEM_PROMPT), HumanMessage(content=context)]
        })

        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                text = msg.content.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    text = text.rsplit("```", 1)[0].strip()
                import json as _json
                return _json.loads(text)
        return {"no_data": True, "reason": "Agent did not produce a chart specification."}
    except Exception as e:
        logger.error(f"Plot agent error: {e}", exc_info=True)
        return {"no_data": True, "reason": f"Error generating chart: {e}"}
