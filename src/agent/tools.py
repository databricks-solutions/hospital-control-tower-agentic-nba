"""Agent tools for SQL execution, vector search, and analysis output.

NOTE: This is the notebook-accessible copy. The authoritative version is app/agent/tools.py.
"""
import os
import json
import uuid
from datetime import datetime
from typing import Optional
from langchain_core.tools import tool
from databricks.sdk import WorkspaceClient

_workspace_client: Optional[WorkspaceClient] = None


def get_workspace_client() -> WorkspaceClient:
    global _workspace_client
    if _workspace_client is None:
        _workspace_client = WorkspaceClient()
    return _workspace_client


CATALOG = os.environ.get("CATALOG", "")
SCHEMA = os.environ.get("SCHEMA", "med_logistics_nba")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
VECTOR_ENDPOINT = os.environ.get("VECTOR_SEARCH_ENDPOINT", "")
VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.encounters_vector_index"
ANALYSIS_TABLE = f"{CATALOG}.{SCHEMA}.analysis_outputs"


@tool
def execute_sql(query: str) -> str:
    """Execute read-only SQL query against medical logistics data.

    Available tables:
    - dim_encounters: Patient encounters (encounter_id, hospital, department, los_days, discharge_day_of_week, is_readmission)
    - fact_drug_costs: Drug costs (encounter_id, drug_name, drug_category, unit_cost, total_cost)
    - fact_staffing: Staffing (date, hospital, department, staff_type, fte_count, cost_per_fte)
    - fact_ed_wait_times: ED waits (encounter_id, wait_minutes, acuity_level)
    - fact_operational_kpis: Daily KPIs (avg_los, avg_ed_wait_minutes, contract_labor_pct, readmission_rate)
    """
    query_upper = query.strip().upper()
    if not query_upper.startswith("SELECT"):
        return json.dumps({"error": "Only SELECT queries are allowed"})
    blocked = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"]
    for keyword in blocked:
        if keyword in query_upper:
            return json.dumps({"error": f"Query contains blocked keyword: {keyword}"})
    try:
        w = get_workspace_client()
        result = w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID, statement=query, wait_timeout="30s",
        )
        if result.status.state.value == "SUCCEEDED":
            if result.result and result.result.data_array:
                columns = [col.name for col in result.manifest.schema.columns]
                rows = [dict(zip(columns, row)) for row in result.result.data_array]
                return json.dumps({"columns": columns, "rows": rows[:100], "row_count": len(rows)})
            return json.dumps({"columns": [], "rows": [], "row_count": 0})
        else:
            return json.dumps({"error": f"Query failed: {result.status.error}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def search_encounters(query: str, num_results: int = 5) -> str:
    """Search patient encounters using semantic similarity."""
    num_results = min(max(num_results, 1), 20)
    try:
        w = get_workspace_client()
        resp = w.vector_search_indexes.query_index(
            index_name=VECTOR_INDEX,
            query_text=query,
            columns=["encounter_id", "text_content", "hospital", "department", "los_days", "is_readmission"],
            num_results=num_results,
        )
        data_array = resp.result.data_array if resp.result else []
        matches = []
        for row in (data_array or []):
            if len(row) >= 2:
                matches.append({
                    "score": row[0] if isinstance(row[0], (int, float)) else None,
                    "encounter_id": row[1] if len(row) > 1 else None,
                    "text_content": row[2] if len(row) > 2 else None,
                    "hospital": row[3] if len(row) > 3 else None,
                    "department": row[4] if len(row) > 4 else None,
                    "los_days": row[5] if len(row) > 5 else None,
                    "is_readmission": row[6] if len(row) > 6 else None,
                })
        return json.dumps({"matches": matches, "query": query})
    except Exception as e:
        return json.dumps({"error": str(e), "query": query})


@tool
def write_analysis(analysis_type: str, insights: str, recommendations: Optional[str] = None,
                   encounter_id: Optional[str] = None, agent_mode: str = "rag") -> str:
    """Write analysis results to the analysis_outputs table."""
    try:
        from databricks.sdk.service.sql import StatementParameterListItem
        record_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        w = get_workspace_client()
        insert_sql = f"""
        INSERT INTO {ANALYSIS_TABLE}
        (id, encounter_id, analysis_type, insights, recommendations, created_at, agent_mode, metadata)
        VALUES (:p_id, :p_encounter_id, :p_analysis_type, :p_insights,
                :p_recommendations, :p_created_at, :p_agent_mode, NULL)
        """
        params = [
            StatementParameterListItem(name="p_id", value=record_id),
            StatementParameterListItem(name="p_encounter_id", value=encounter_id),
            StatementParameterListItem(name="p_analysis_type", value=analysis_type),
            StatementParameterListItem(name="p_insights", value=insights),
            StatementParameterListItem(name="p_recommendations", value=recommendations),
            StatementParameterListItem(name="p_created_at", value=created_at),
            StatementParameterListItem(name="p_agent_mode", value=agent_mode),
        ]
        result = w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID, statement=insert_sql,
            parameters=params, wait_timeout="30s",
        )
        state = result.status.state.value if result.status and result.status.state else "UNKNOWN"
        if state in ("SUCCEEDED", "CLOSED"):
            return json.dumps({"success": True, "id": record_id, "analysis_type": analysis_type, "message": "Analysis saved successfully"})
        else:
            return json.dumps({"error": f"Write failed: {result.status.error}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


ORCHESTRATOR_TOOLS = [execute_sql, search_encounters]
RAG_TOOLS = [execute_sql, search_encounters, write_analysis]
ALL_TOOLS = {"execute_sql": execute_sql, "search_encounters": search_encounters, "write_analysis": write_analysis}
