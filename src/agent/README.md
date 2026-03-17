# src/agent/ -- Investment Portfolio Intelligence Agent

This directory contains the agent code for investment portfolio intelligence. It provides tools for SQL execution, vector search over fund documents, and multi-agent deep analysis.

## Tools

- **execute_sql**: Execute read-only SQL against investment portfolio tables (dim_funds, fact_fund_performance, fact_portfolio_holdings, fact_fund_flows, fact_portfolio_kpis, portfolio_overview)
- **search_fund_documents**: Semantic search over fund documents using the fund_documents_vector_index
- **write_analysis**: Persist analysis results to analysis_outputs (fund_id, analysis_type, insights, recommendations)

## Modes

- **Quick Query (orchestrator)**: Single-step tool selection for factual questions
- **Deep Analysis (rag)**: Multi-agent graph with planner, retrieval, and analyst nodes

## Keeping in sync

When modifying agent code:
1. Make changes in `app/agent/` first (the running app uses this).
2. Copy relevant changes to `src/agent/` if notebooks need the same behavior.

The primary authoritative copy is `app/agent/`. This directory is secondary.
