"""Centralized configuration for agent modules."""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

CATALOG = os.environ.get("CATALOG", "")
SCHEMA = os.environ.get("SCHEMA", "med_logistics_nba")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
VECTOR_ENDPOINT = os.environ.get("VECTOR_SEARCH_ENDPOINT", "")
# Canonical LLM defaults — must match variables.yml / resources/apps.yml.
# Orchestrator = fast intent routing / supervisor; RAG/Analyst = high-quality analysis.
LLM_MODEL = os.environ.get("LLM_MODEL_RAG", "databricks-claude-sonnet-4-5")
LLM_ORCHESTRATOR = os.environ.get("LLM_MODEL_ORCHESTRATOR", "databricks-gpt-oss-120b")
LLM_ANALYST = os.environ.get("LLM_MODEL_ANALYST", LLM_MODEL)
MLFLOW_EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT", "/Shared/hospital-control-tower-agent")

MAX_SUPERVISOR_ITERATIONS = 3

VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.encounters_vector_index"
SOP_VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.sop_vector_index"

ENCOUNTERS_TABLE = f"{CATALOG}.{SCHEMA}.dim_encounters"
DRUG_COSTS_TABLE = f"{CATALOG}.{SCHEMA}.fact_drug_costs"
STAFFING_TABLE = f"{CATALOG}.{SCHEMA}.fact_staffing"
ED_WAIT_TABLE = f"{CATALOG}.{SCHEMA}.fact_ed_wait_times"
KPI_TABLE = f"{CATALOG}.{SCHEMA}.fact_operational_kpis"
HOSPITAL_OVERVIEW_TABLE = f"{CATALOG}.{SCHEMA}.hospital_overview"
ANALYSIS_TABLE = f"{CATALOG}.{SCHEMA}.analysis_outputs"

# --- Singleton WorkspaceClient ---
_workspace_client = None


def get_workspace_client():
    global _workspace_client
    if _workspace_client is None:
        from databricks.sdk import WorkspaceClient
        _workspace_client = WorkspaceClient()
    return _workspace_client


# Critical config: env var name -> consequence if missing. Used by validators below.
_CRITICAL_CONFIG = {
    "CATALOG": (CATALOG, "SQL queries will fail"),
    "SCHEMA": (SCHEMA, "SQL queries will fail"),
    "DATABRICKS_WAREHOUSE_ID": (WAREHOUSE_ID, "SQL statement execution will fail"),
    "VECTOR_SEARCH_ENDPOINT": (VECTOR_ENDPOINT, "vector search will fail"),
}


def missing_critical_config():
    """Return the list of critical env var names that are unset/empty."""
    return [name for name, (value, _) in _CRITICAL_CONFIG.items() if not value]


def validate_config():
    """Log the state of critical config on startup. Returns True if all present."""
    missing = missing_critical_config()
    for name in missing:
        _, consequence = _CRITICAL_CONFIG[name]
        logger.error(f"CONFIG: {name} is empty -- {consequence}")
    if not missing:
        logger.info(f"Config OK: catalog={CATALOG}, schema={SCHEMA}, warehouse={WAREHOUSE_ID[:8]}...")
    return not missing


def config_error_message():
    """A single actionable message naming the missing vars, or None if config is complete."""
    missing = missing_critical_config()
    if not missing:
        return None
    return (
        "Hospital Control Tower is not configured. Missing required setting(s): "
        + ", ".join(missing)
        + ". Set them via BUNDLE_VAR_* (see .databricks-env.sh.example) and redeploy."
    )
