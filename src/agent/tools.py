"""Agent tools for SQL execution, vector search, and analysis output."""
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
SCHEMA = os.environ.get("SCHEMA", "investment_intel")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
VECTOR_ENDPOINT = os.environ.get("VECTOR_SEARCH_ENDPOINT", "")
VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.fund_documents_vector_index"
ANALYSIS_TABLE = f"{CATALOG}.{SCHEMA}.analysis_outputs"


@tool
def execute_sql(query: str) -> str:
    """Execute read-only SQL query against investment portfolio data.

    Available tables:
    - dim_funds: Fund holdings (fund_id, fund_name, sector, holding_period, rebalance_day_of_week, is_rebalance)
    - fact_fund_performance: Fund performance (fund_id, holding_name, holding_category, unit_return, total_return)
    - fact_portfolio_holdings: Portfolio holdings (date, fund_name, sector, position_type, holding_count, cost_per_holding)
    - fact_fund_flows: Fund flows (fund_id, flow_amount, risk_level)
    - fact_portfolio_kpis: Daily KPIs (avg_holding_period, avg_flow_amount, exposure_pct, rebalance_rate)
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
def search_fund_documents(query: str, num_results: int = 5) -> str:
    """Search fund documents using semantic similarity."""
    num_results = min(max(num_results, 1), 20)
    try:
        from databricks.vector_search.client import VectorSearchClient
        vsc = VectorSearchClient()
        index = vsc.get_index(endpoint_name=VECTOR_ENDPOINT, index_name=VECTOR_INDEX)
        results = index.similarity_search(
            query_text=query,
            columns=["fund_id", "text_content", "fund_name", "sector", "holding_period", "is_rebalance"],
            num_results=num_results,
        )
        matches = []
        for row in results.get("result", {}).get("data_array", []):
            if len(row) >= 2:
                matches.append({
                    "score": row[0] if isinstance(row[0], (int, float)) else None,
                    "fund_id": row[1] if len(row) > 1 else None,
                    "text_content": row[2] if len(row) > 2 else None,
                    "fund_name": row[3] if len(row) > 3 else None,
                    "sector": row[4] if len(row) > 4 else None,
                    "holding_period": row[5] if len(row) > 5 else None,
                    "is_rebalance": row[6] if len(row) > 6 else None,
                })
        return json.dumps({"matches": matches, "query": query})
    except Exception as e:
        return json.dumps({"error": str(e), "query": query})


@tool
def write_analysis(analysis_type: str, insights: str, recommendations: Optional[str] = None,
                   fund_id: Optional[str] = None, agent_mode: str = "rag") -> str:
    """Write analysis results to the analysis_outputs table."""
    try:
        record_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        def escape(s):
            return s.replace("'", "''") if s else None
        insights_escaped = escape(insights)
        reco_escaped = escape(recommendations) if recommendations else None
        fund_escaped = escape(fund_id) if fund_id else None
        reco_value = f"'{reco_escaped}'" if reco_escaped else "NULL"
        fund_value = f"'{fund_escaped}'" if fund_escaped else "NULL"

        insert_sql = f"""
        INSERT INTO {ANALYSIS_TABLE}
        (id, fund_id, analysis_type, insights, recommendations, created_at, agent_mode, metadata)
        VALUES ('{record_id}', {fund_value}, '{escape(analysis_type)}', '{insights_escaped}',
                {reco_value}, '{created_at}', '{escape(agent_mode)}', NULL)
        """
        w = get_workspace_client()
        result = w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID, statement=insert_sql, wait_timeout="30s",
        )
        if result.status.state.value in ["SUCCEEDED", "CLOSED"]:
            return json.dumps({"success": True, "id": record_id, "analysis_type": analysis_type, "message": "Analysis saved successfully"})
        else:
            return json.dumps({"error": f"Write failed: {result.status.error}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


ORCHESTRATOR_TOOLS = [execute_sql, search_fund_documents]
RAG_TOOLS = [execute_sql, search_fund_documents, write_analysis]
ALL_TOOLS = {"execute_sql": execute_sql, "search_fund_documents": search_fund_documents, "write_analysis": write_analysis}
