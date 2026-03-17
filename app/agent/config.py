"""Centralized configuration for agent modules."""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

CATALOG = os.environ.get("CATALOG", "")
SCHEMA = os.environ.get("SCHEMA", "investment_intel")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
VECTOR_ENDPOINT = os.environ.get("VECTOR_SEARCH_ENDPOINT", "")
LLM_MODEL = os.environ.get("LLM_MODEL_RAG", "databricks-claude-sonnet-4-5")
LLM_ORCHESTRATOR = os.environ.get("LLM_MODEL_ORCHESTRATOR", LLM_MODEL)
MLFLOW_EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT", "/Shared/investment-intelligence-agent")

MAX_SUPERVISOR_ITERATIONS = 3

VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.fund_documents_vector_index"
SOP_VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.investment_policy_vector_index"

FUNDS_TABLE = f"{CATALOG}.{SCHEMA}.dim_funds"
PERFORMANCE_TABLE = f"{CATALOG}.{SCHEMA}.fact_fund_performance"
HOLDINGS_TABLE = f"{CATALOG}.{SCHEMA}.fact_portfolio_holdings"
FLOWS_TABLE = f"{CATALOG}.{SCHEMA}.fact_fund_flows"
KPI_TABLE = f"{CATALOG}.{SCHEMA}.fact_portfolio_kpis"
PORTFOLIO_OVERVIEW_TABLE = f"{CATALOG}.{SCHEMA}.portfolio_overview"
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
