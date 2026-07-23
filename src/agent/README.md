# src/agent/ -- Notebook-Accessible Agent Code

This directory mirrors `app/agent/` for use by Databricks notebooks. Notebooks cannot import from `app/` (which runs inside the Databricks App), so this copy exists to let notebooks reuse agent tools and graph logic.

## Changes from v1

- **LLM-based intent routing** replaces keyword matching in `orchestrator.py`
- **Per-role LLMs**: supervisor uses `LLM_ORCHESTRATOR` (lightweight), analyst uses `LLM_ANALYST` (capable)
- **MemorySaver checkpointer** enables multi-turn context via `thread_id`
- **Parameterized SQL** in `write_analysis` replaces string concatenation
- **Module-level graph/LLM initialization** replaces lazy singletons

## Keeping in sync

When modifying agent code:
1. Make changes in `app/agent/` first (the running app uses this).
2. Copy relevant changes to `src/agent/` if notebooks need the same behavior.

The primary authoritative copy is `app/agent/`. This directory is secondary.
