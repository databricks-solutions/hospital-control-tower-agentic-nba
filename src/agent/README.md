# src/agent/ -- Notebook-Accessible Agent Code

This directory mirrors `app/agent/` for use by Databricks notebooks. Notebooks cannot import from `app/` (which runs inside the Databricks App), so this copy exists to let notebooks reuse agent tools and graph logic.

## Keeping in sync

When modifying agent code:
1. Make changes in `app/agent/` first (the running app uses this).
2. Copy relevant changes to `src/agent/` if notebooks need the same behavior.

The primary authoritative copy is `app/agent/`. This directory is secondary.
