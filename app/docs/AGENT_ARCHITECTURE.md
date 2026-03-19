# Agent Architecture

This app uses three agent modes, each built with LangGraph on Databricks. All modes use Databricks Foundation Model APIs for LLM inference and are traced with MLflow.

## Quick Query (2-5 seconds)

A single ReAct agent with intent-based tool selection. Designed for fast lookups and simple questions.

**Flow:**

1. User sends a message
2. **Intent Classifier** (LLM call) categorizes the question:
   - `query` -- data lookup, allocates `execute_sql` only
   - `search` -- semantic search, allocates `search_encounters` + `search_sops`
   - `analyze` -- full analysis, allocates all tools
   - `general` -- default, allocates SQL + vector search
3. **ReAct Agent** executes with the selected tool subset
4. Agent calls tools as needed (typically 1-2 calls), then responds

**Why this design:** Intent classification before tool selection reduces latency by ~60% compared to giving the agent all tools. The agent doesn't waste reasoning cycles deciding between tools that aren't relevant.

**Tools available:** `execute_sql`, `search_encounters`, `search_sops`, `analyze_cost_drivers`, `analyze_los_factors`, `check_ed_performance`, `check_staffing_efficiency`, `check_operational_kpis`, `check_data_freshness`

## Deep Analysis (30-90 seconds)

A multi-agent pipeline with a supervisor, planner, and specialized workers. Used for complex questions that require multiple data sources and cross-referencing.

**Flow:**

1. User sends a message
2. **Prerequisite Check** -- queries `analysis_outputs` table to see what recent analyses exist
3. **Supervisor** decides whether planning is needed or a direct response suffices
4. **Planner** (if invoked) creates a step-by-step analysis plan
5. For each plan step, the **Supervisor** dispatches to a specialized worker:
   - **Retrieval Agent** -- runs SQL queries and vector searches to gather evidence
   - **Analyst Agent** -- interprets results, identifies patterns, writes findings via `write_analysis`
6. **Respond Agent** synthesizes all findings into a final answer
7. Loop terminates after max 3 supervisor iterations

**Why this design:** Complex hospital operations questions (e.g., "Why did readmissions spike at Hospital B?") require correlating data across encounters, costs, staffing, and ED tables. A single agent struggles to maintain context across 5+ tool calls. The planner/executor split keeps each agent focused.

**Key difference from Quick Query:** Deep Analysis runs asynchronously (background thread with polling) so the UI stays responsive. Results include a routing trace showing which agents were invoked.

## Autonomous Mode (background, configurable interval)

A scheduled agent that proactively monitors hospital operations and generates recommended actions without user prompting.

**Flow:**

1. **APScheduler** triggers at a configurable interval (default: 60 min)
2. Agent runs a monitoring cycle:
   - Checks operational KPIs against thresholds
   - Identifies anomalies (cost spikes, LOS outliers, ED breaches)
   - Cross-references with SOPs for recommended actions
3. Writes findings to `analysis_outputs` table with priority levels (critical/high/medium/low)
4. Recommendations appear in the dashboard for human review (approve/reject)

**Why this design:** Hospital operations teams need proactive alerting, not just reactive Q&A. The autonomous agent mimics a "night shift analyst" that continuously watches for issues and prepares action items for the morning team.

**Human-in-the-loop:** All autonomous recommendations require explicit approval before being acted on. The approve/reject workflow ensures the agent augments human judgment rather than replacing it.

## Shared Infrastructure

All three modes share:

- **Databricks SQL** via Statement Execution API for structured queries
- **Vector Search** for semantic search over encounters and SOPs
- **Unity Catalog** for governed table access
- **Lakebase (PostgreSQL)** as a low-latency operational store (with UC fallback)
- **MLflow Tracing** for observability across all agent calls

> **Note on Unity Catalog tools:** Agent tools in this demo use the Databricks SDK and Statement Execution API directly rather than UC Functions. This is intentional for portability -- the demo can run across workspaces without registering UC Functions first. In a production deployment, wrapping tools as UC Functions would add governance (lineage tracking, access control, and discoverability) and enable use with Databricks Agent Framework's built-in UC tool integration.

See the project README for full visual architecture diagrams.
