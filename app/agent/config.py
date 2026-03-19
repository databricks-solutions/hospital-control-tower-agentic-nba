"""Centralized configuration for agent modules."""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

CATALOG = os.environ.get("CATALOG", "")
SCHEMA = os.environ.get("SCHEMA", "med_logistics_nba")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
VECTOR_ENDPOINT = os.environ.get("VECTOR_SEARCH_ENDPOINT", "")
LLM_MODEL = os.environ.get("LLM_MODEL_RAG", "databricks-claude-sonnet-4-5")
LLM_ORCHESTRATOR = os.environ.get("LLM_MODEL_ORCHESTRATOR", LLM_MODEL)
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


def validate_config():
    """Log warnings for missing critical config on startup."""
    issues = []
    if not CATALOG:
        issues.append("CATALOG is empty -- SQL queries will fail")
    if not SCHEMA:
        issues.append("SCHEMA is empty -- SQL queries will fail")
    if not WAREHOUSE_ID:
        issues.append("DATABRICKS_WAREHOUSE_ID is empty -- SQL statement execution will fail")
    if not VECTOR_ENDPOINT:
        issues.append("VECTOR_SEARCH_ENDPOINT is empty -- vector search will fail")
    for issue in issues:
        logger.error(f"CONFIG: {issue}")
    if not issues:
        logger.info(f"Config OK: catalog={CATALOG}, schema={SCHEMA}, warehouse={WAREHOUSE_ID[:8]}...")
    return len(issues) == 0
