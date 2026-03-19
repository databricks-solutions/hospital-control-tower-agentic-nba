# Building Agents with Hospital Control Tower

This guide walks through the agent architecture in this project. It's designed for developers who want to understand how multi-agent systems, tool-augmented LLMs, and agent-in-app patterns work on Databricks.

## Agent Patterns Used

This project implements three distinct agent patterns, each suited to different use cases:

| Pattern | File | When to Use |
|---------|------|-------------|
| **ReAct (single agent)** | `app/agent/orchestrator.py` | Fast, focused tasks with 1-3 tool calls |
| **Multi-agent supervisor graph** | `app/agent/graph.py` | Complex investigations requiring planning, retrieval, and analysis |
| **Scheduled autonomous** | `app/agent/autonomous.py` | Background monitoring and proactive action |

## How the Multi-Agent Graph Works

The deep analysis mode (`app/agent/graph.py`) uses a LangGraph `StateGraph` with an LLM-based supervisor that decides the next step at each iteration.

### State Definition

```python
class DeepAnalysisState(TypedDict):
    messages: Annotated[list, add]       # Accumulated messages
    user_query: str                       # Original user question
    plan: str                             # Data-gathering plan (set by planner)
    retrieved_evidence: str               # Evidence (set by retrieval agent)
    prerequisite_status: str              # What analyses exist already
    analysis_result: str                  # Final analysis (set by analyst)
    needs_clarification: bool             # Whether to ask user for more info
    clarification_question: str           # The clarification to ask
    next_step: str                        # Supervisor's routing decision
    iteration: Annotated[list, add]       # Iteration counter (append-only)
    tool_calls_made: Annotated[list, add] # All tools invoked across nodes
```

Fields using `Annotated[list, add]` are append-only -- each node's return value is concatenated to the existing list. This lets `tool_calls_made` accumulate across all sub-agents without overwriting.

### Graph Structure

```
Entry --> Supervisor --> PLAN --> Planner --> Supervisor
                    --> RETRIEVE --> Retrieval Agent --> Supervisor
                    --> ANALYZE --> Analyst Agent --> Supervisor
                    --> CLARIFY --> Clarify Node --> Respond --> END
                    --> RESPOND --> Respond Node --> END
```

The supervisor is called after every sub-agent completes. It examines the current state (does a plan exist? is evidence gathered? is analysis complete?) and routes to the next step. After 3 iterations, it forces a response to prevent infinite loops.

### Node Functions

Each node is a plain Python function that takes `DeepAnalysisState` and returns a partial state update:

- **`supervisor_node`** -- Calls the LLM with the current state summary and asks for one word: CLARIFY, PLAN, RETRIEVE, ANALYZE, or RESPOND. This is the routing brain.
- **`planner_node`** -- Calls the LLM to produce a numbered data-gathering plan based on the user's question and what prerequisite analyses are available.
- **`retrieval_node`** -- Creates a ReAct agent with all data tools and executes the plan. Returns gathered evidence.
- **`analyst_node`** -- Creates a ReAct agent with the `write_analysis` tool. Interprets evidence and produces a structured report with citations.
- **`respond_node`** -- Formats the final output. If analysis is complete, returns it directly. Otherwise generates a partial summary.
- **`clarify_node`** -- Asks the user a clarifying question when the query is too vague.

### Building the Graph

```python
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
    graph.add_edge("planner", "supervisor")      # planner returns to supervisor
    graph.add_edge("retrieval", "supervisor")     # retrieval returns to supervisor
    graph.add_edge("analyst", "supervisor")       # analyst returns to supervisor
    graph.add_edge("clarify", "respond")          # clarify goes straight to respond
    graph.add_edge("respond", END)                # respond ends the graph
    return graph.compile()
```

### Progress Streaming

The graph emits progress events via a module-level `queue.Queue`. Each node calls `_emit_progress(stage, message)` at entry. The Flask API reads from this queue and streams events to the frontend via SSE.

This is a pragmatic approach: it doesn't stream token-by-token (which would require async generators), but it gives the user visibility into which phase is running, which is more useful for long multi-agent operations.

## How Tools Are Built

Tools are defined in `app/agent/tools.py` using the LangChain `@tool` decorator. Each tool is a Python function that returns a JSON string.

### Anatomy of a Tool

```python
@tool
def execute_sql(query: str) -> str:
    """Execute read-only SQL query against medical logistics data.

    Available tables:
    - dim_encounters: Patient encounters (encounter_id, hospital, ...)
    - fact_drug_costs: Drug costs (encounter_id, drug_name, total_cost, ...)
    ...
    """
    # Validate: only SELECT allowed
    # Execute via Databricks SDK statement_execution
    # Return JSON with columns, rows, row_count
```

Key patterns:
- **Docstrings are prompts.** The LLM reads the docstring to understand when and how to use the tool. Include table schemas, parameter descriptions, and usage examples.
- **Return JSON strings.** LangChain tools return strings. Use `json.dumps()` for structured data.
- **Handle errors gracefully.** Return `{"error": "..."}` instead of raising -- the LLM can interpret error messages and retry.
- **Use a shared execution helper.** `_execute_query()` centralizes SQL execution so all tools use the same connection and error handling.

### Tool Collections

Tools are grouped into collections for different agent modes:

```python
QUICK_TOOLS = [execute_sql, search_encounters, search_sops, ...]
DEEP_TOOLS  = [execute_sql, search_encounters, search_sops, ..., write_analysis]
```

Quick mode gets a smaller tool set for speed. Deep mode gets everything, including `write_analysis` for persisting insights.

## How to Add a New Tool

1. Define the function in `app/agent/tools.py`:

```python
@tool
def analyze_readmission_risk(department: Optional[str] = None) -> str:
    """Analyze readmission risk factors by department.

    Examines correlation between LOS, payer mix, and readmission rates.
    """
    query = f"SELECT ... FROM {ENCOUNTERS_TABLE} ..."
    result = _execute_query(query)
    return json.dumps({"risk_factors": result.get("rows", [])})
```

2. Add it to the relevant tool collections at the bottom of `tools.py`:

```python
DEEP_TOOLS = [..., analyze_readmission_risk]
```

3. If the tool is relevant to deep analysis, the retrieval and analyst agents will discover it automatically (they receive all `DEEP_TOOLS`). If you want the planner to know about it, update the `PLANNER_PROMPT` in `graph.py`.

4. Mirror the change in `src/agent/tools.py` if notebooks need the same tool.

## How to Add a New Agent Mode

To add a fourth mode (e.g., "report generation"):

1. **Define the graph or agent** in a new file (e.g., `app/agent/reporter.py`).

2. **Add an API endpoint** in `app/api_server.py` that invokes it, or extend `invoke_agent()` in `graph.py` with a new mode branch.

3. **Add a UI toggle** in `app/src/components/Header.jsx` (add a third button to the mode toggle group).

4. **Wire the mode** through `App.jsx` -> `ConversationView.jsx` -> the API call.

## How Prompts Are Structured

Prompts live as module-level constants in `graph.py`:

- `SUPERVISOR_PROMPT` -- Routing instructions and valid decisions
- `PLANNER_PROMPT` -- Available tables, tools, and planning format
- `RETRIEVAL_PROMPT` -- Output format for gathered evidence
- `ANALYST_PROMPT` -- Structured report format with sections

Quick-query prompts are built dynamically in `orchestrator.py:get_system_prompt_for_context()` based on classified intent.

Autonomous prompts are embedded in the capability definitions in `autonomous.py:CAPABILITIES`.

### Prompt Design Principles

- **Be specific about output format.** The supervisor must return one word. The analyst must use markdown sections. Ambiguous format instructions lead to unparseable output.
- **Include table schemas in tool docstrings and planner prompts.** The LLM needs to know column names to write correct SQL.
- **Tell the agent what NOT to do.** The quick query prompt explicitly says "Do NOT perform multi-step deep analysis."

## Key Design Decisions

**Why supervisor pattern instead of a chain?** A chain (plan -> retrieve -> analyze) always runs all steps. The supervisor can skip planning for simple questions, ask for clarification when needed, or go straight to analysis if evidence is already available. It's more flexible at the cost of one LLM call per routing decision.

**Why SSE with progress events instead of token streaming?** Multi-agent graphs run multiple LLM calls internally. Token streaming from a sub-agent would require async generators threaded through the graph, adding significant complexity. Progress events ("planning...", "retrieving...", "analyzing...") give the user enough visibility for a 30-90 second operation without that complexity.

**Why Lakebase + Unity Catalog fallback for `write_analysis`?** Lakebase provides low-latency transactional writes (ideal for app state). Unity Catalog is always available. The fallback means the app works with or without Lakebase configured.

**Why `app/agent/` and `src/agent/` both exist?** `app/agent/` is used by the running app. `src/agent/` is a copy used by notebooks (which can't import from `app/`). This is a known duplication -- keep them in sync when making changes.

## Further Reading

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Tools Guide](https://python.langchain.com/docs/how_to/#tools)
- [Databricks Foundation Models](https://docs.databricks.com/en/machine-learning/foundation-models/index.html)
- [Databricks Vector Search](https://docs.databricks.com/en/generative-ai/vector-search.html)
