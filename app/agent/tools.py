"""Agent tools for SQL execution, vector search, and investment portfolio analysis."""
import re
import json
import uuid
import logging
from datetime import datetime
from typing import Optional
from langchain_core.tools import tool
from databricks.sdk.service.sql import Format, Disposition

from .config import (
    CATALOG, SCHEMA,
    WAREHOUSE_ID, VECTOR_ENDPOINT, VECTOR_INDEX, SOP_VECTOR_INDEX,
    FUNDS_TABLE, PERFORMANCE_TABLE, HOLDINGS_TABLE,
    FLOWS_TABLE, KPI_TABLE, ANALYSIS_TABLE,
    get_workspace_client,
)

logger = logging.getLogger(__name__)

_SAFE_IDENTIFIER = re.compile(r'^[A-Za-z0-9_ ]+$')

def _validate_identifier(value, name):
    if value and not _SAFE_IDENTIFIER.match(value):
        raise ValueError(f"Invalid {name}: {value!r}")


def _execute_query(query: str, wait_timeout: str = "30s") -> dict:
    """Execute a SQL query and return results. Forces JSON_ARRAY format."""
    w = get_workspace_client()
    result = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=query, wait_timeout=wait_timeout,
        format=Format.JSON_ARRAY, disposition=Disposition.INLINE,
    )
    state = result.status.state.value if result.status and result.status.state else "UNKNOWN"
    if state in ("SUCCEEDED", "CLOSED"):
        if result.result and result.result.data_array:
            columns = [col.name for col in result.manifest.schema.columns]
            rows = [dict(zip(columns, row)) for row in result.result.data_array]
            return {"success": True, "columns": columns, "rows": rows, "row_count": len(rows)}
        return {"success": True, "columns": [], "rows": [], "row_count": 0}
    else:
        return {"success": False, "error": str(result.status.error)}


ALLOWED_TABLES = {
    "dim_funds", "fact_fund_performance", "fact_portfolio_holdings",
    "fact_fund_flows", "fact_portfolio_kpis", "portfolio_overview", "analysis_outputs",
}

def _check_table_allowlist(query: str) -> Optional[str]:
    """Return an error message if the query references tables not in the allowlist."""
    q = query.lower()
    prefix = f"{CATALOG.lower()}.{SCHEMA.lower()}."
    for table in ALLOWED_TABLES:
        q = q.replace(f"{prefix}{table}", table)
    refs = re.findall(r'\bfrom\s+(\w+)|\bjoin\s+(\w+)', q)
    for match in refs:
        name = match[0] or match[1]
        if name not in ALLOWED_TABLES:
            return f"Table '{name}' is not in the allowed list"
    return None

@tool
def execute_sql(query: str) -> str:
    """Execute read-only SQL query against investment portfolio data.

    Available tables:
    - dim_funds: Fund dimension (fund_id, fund_name, manager_name, strategy, vintage_year, aum, commitment, status, domicile, inception_date)
    - fact_fund_performance: Monthly returns (fund_id, date, nav, monthly_return, ytd_return, itd_return, benchmark_return, alpha)
    - fact_portfolio_holdings: Position holdings (fund_id, date, position_name, sector, geography, pct_nav, market_value, change_from_prior)
    - fact_fund_flows: Capital flows (fund_id, date, capital_calls, distributions, net_flow, commitment_remaining, liquidity_terms)
    - fact_portfolio_kpis: Portfolio KPIs (date, portfolio_segment, total_aum, weighted_avg_return, concentration_top5_pct, benchmark_spread, manager_count)
    - portfolio_overview: Summary VIEW (strategy, fund_count, total_aum, avg_aum, manager_count, watchlist_count)
    """
    query_upper = query.strip().upper()
    if not query_upper.startswith("SELECT"):
        return json.dumps({"error": "Only SELECT queries are allowed"})
    blocked = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"]
    for keyword in blocked:
        if keyword in query_upper:
            return json.dumps({"error": f"Query contains blocked keyword: {keyword}"})
    table_err = _check_table_allowlist(query)
    if table_err:
        return json.dumps({"error": table_err})
    try:
        result = _execute_query(query)
        if result["success"]:
            return json.dumps({"columns": result["columns"], "rows": result["rows"][:100], "row_count": result["row_count"]})
        else:
            return json.dumps({"error": result["error"]})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def search_fund_documents(query: str, num_results: int = 5) -> str:
    """Search fund documents (memos, letters, pitch decks) using semantic similarity.

    Use natural language to describe what you're looking for:
    - "manager outlook for 2026 from MedVenture Alpha"
    - "fund performance highlights and key drivers"
    - "risk factors and portfolio concentration"
    """
    num_results = min(max(num_results, 1), 20)
    try:
        w = get_workspace_client()
        resp = w.vector_search_indexes.query_index(
            index_name=VECTOR_INDEX,
            query_text=query,
            columns=["fund_id", "text_content", "manager_name", "strategy", "doc_type"],
            num_results=num_results,
        )
        data_array = resp.result.data_array if resp.result else []
        matches = []
        for row in (data_array or []):
            if len(row) >= 2:
                matches.append({
                    "score": row[0] if row[0] else None,
                    "fund_id": row[1] if len(row) > 1 else None,
                    "text_content": row[2] if len(row) > 2 else None,
                    "manager_name": row[3] if len(row) > 3 else None,
                    "strategy": row[4] if len(row) > 4 else None,
                    "doc_type": row[5] if len(row) > 5 else None,
                })
        return json.dumps({"matches": matches, "query": query})
    except Exception as e:
        return json.dumps({"error": str(e), "query": query})


@tool
def analyze_performance_drivers(fund_id: Optional[str] = None, strategy: Optional[str] = None) -> str:
    """Analyze fund performance drivers and return attribution.

    Identifies:
    - Top/bottom performing funds by return
    - Performance vs benchmark (alpha generation)
    - Return trends over time
    - Strategy-level comparisons
    """
    try:
        _validate_identifier(fund_id, "fund_id")
        _validate_identifier(strategy, "strategy")
        where_clauses = []
        if fund_id:
            where_clauses.append(f"p.fund_id = '{fund_id}'")
        if strategy:
            where_clauses.append(f"f.strategy = '{strategy}'")
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        top_funds_query = f"""
        SELECT f.fund_name, f.manager_name, f.strategy,
               ROUND(AVG(p.monthly_return) * 12 * 100, 2) as annualized_return_pct,
               ROUND(AVG(p.alpha) * 12 * 100, 2) as annualized_alpha_pct,
               COUNT(*) as months_reported
        FROM {PERFORMANCE_TABLE} p JOIN {FUNDS_TABLE} f ON p.fund_id = f.fund_id
        {where_sql}
        GROUP BY f.fund_name, f.manager_name, f.strategy
        ORDER BY annualized_return_pct DESC LIMIT 15
        """
        top_funds = _execute_query(top_funds_query)

        trend_query = f"""
        SELECT MONTH(p.date) as month, f.strategy,
               ROUND(AVG(p.monthly_return) * 100, 3) as avg_monthly_return_pct,
               ROUND(AVG(p.alpha) * 100, 3) as avg_alpha_pct
        FROM {PERFORMANCE_TABLE} p JOIN {FUNDS_TABLE} f ON p.fund_id = f.fund_id
        {where_sql}
        GROUP BY MONTH(p.date), f.strategy ORDER BY month
        """
        trend = _execute_query(trend_query)

        return json.dumps({
            "top_funds": top_funds.get("rows", []),
            "monthly_trend": trend.get("rows", []),
            "filters": {"fund_id": fund_id, "strategy": strategy}
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def analyze_concentration(fund_id: Optional[str] = None) -> str:
    """Analyze portfolio concentration risk at fund and position level.

    Examines:
    - Top positions by % of NAV
    - Sector concentration
    - Geographic concentration
    - Fund-level concentration within strategy
    """
    try:
        _validate_identifier(fund_id, "fund_id")
        where_sql = f"WHERE fund_id = '{fund_id}'" if fund_id else ""

        top_positions_query = f"""
        SELECT position_name, sector, geography,
               ROUND(AVG(pct_nav), 2) as avg_pct_nav,
               ROUND(SUM(market_value), 2) as total_market_value
        FROM {HOLDINGS_TABLE} {where_sql}
        GROUP BY position_name, sector, geography
        ORDER BY avg_pct_nav DESC LIMIT 15
        """
        top_positions = _execute_query(top_positions_query)

        sector_query = f"""
        SELECT sector, ROUND(SUM(market_value), 2) as total_mv,
               ROUND(AVG(pct_nav), 2) as avg_pct_nav, COUNT(DISTINCT position_name) as position_count
        FROM {HOLDINGS_TABLE} {where_sql}
        GROUP BY sector ORDER BY total_mv DESC
        """
        by_sector = _execute_query(sector_query)

        geo_query = f"""
        SELECT geography, ROUND(SUM(market_value), 2) as total_mv,
               ROUND(AVG(pct_nav), 2) as avg_pct_nav
        FROM {HOLDINGS_TABLE} {where_sql}
        GROUP BY geography ORDER BY total_mv DESC
        """
        by_geo = _execute_query(geo_query)

        return json.dumps({
            "top_positions": top_positions.get("rows", []),
            "by_sector": by_sector.get("rows", []),
            "by_geography": by_geo.get("rows", []),
            "fund_filter": fund_id
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def check_fund_flows(fund_id: Optional[str] = None) -> str:
    """Check fund capital call/distribution activity and liquidity.

    Analyzes:
    - Capital calls vs distributions by fund
    - Net flow trends
    - Commitment remaining / unfunded exposure
    - Liquidity terms distribution
    """
    try:
        _validate_identifier(fund_id, "fund_id")
        where_sql = f"WHERE fl.fund_id = '{fund_id}'" if fund_id else ""

        flow_summary = f"""
        SELECT f.fund_name, f.strategy,
               ROUND(SUM(fl.capital_calls), 2) as total_calls,
               ROUND(SUM(fl.distributions), 2) as total_distributions,
               ROUND(SUM(fl.net_flow), 2) as total_net_flow,
               ROUND(AVG(fl.commitment_remaining), 2) as avg_commitment_remaining
        FROM {FLOWS_TABLE} fl JOIN {FUNDS_TABLE} f ON fl.fund_id = f.fund_id
        {where_sql}
        GROUP BY f.fund_name, f.strategy
        ORDER BY total_calls DESC LIMIT 15
        """
        by_fund = _execute_query(flow_summary)

        liquidity_query = f"""
        SELECT fl.liquidity_terms, COUNT(DISTINCT fl.fund_id) as fund_count,
               ROUND(SUM(fl.capital_calls), 2) as total_calls
        FROM {FLOWS_TABLE} fl
        {"WHERE fl.fund_id = '" + fund_id + "'" if fund_id else ""}
        GROUP BY fl.liquidity_terms
        """
        by_liquidity = _execute_query(liquidity_query)

        return json.dumps({
            "by_fund": by_fund.get("rows", []),
            "by_liquidity_terms": by_liquidity.get("rows", []),
            "fund_filter": fund_id
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def check_exposure_shifts(strategy: Optional[str] = None) -> str:
    """Analyze sector and geographic exposure shifts over time.

    Examines:
    - Sector allocation changes quarter-over-quarter
    - Geographic allocation changes
    - Funds with largest position changes
    - Style drift indicators
    """
    try:
        _validate_identifier(strategy, "strategy")
        join_clause = f"JOIN {FUNDS_TABLE} f ON h.fund_id = f.fund_id" if strategy else ""
        where_sql = f"WHERE f.strategy = '{strategy}'" if strategy else ""

        sector_shift = f"""
        SELECT h.sector, YEAR(h.date) as yr, QUARTER(h.date) as qtr,
               ROUND(AVG(h.pct_nav), 2) as avg_allocation_pct,
               ROUND(SUM(h.market_value), 2) as total_mv
        FROM {HOLDINGS_TABLE} h {join_clause}
        {where_sql}
        GROUP BY h.sector, YEAR(h.date), QUARTER(h.date)
        ORDER BY yr DESC, qtr DESC, total_mv DESC
        """
        by_sector = _execute_query(sector_shift)

        geo_shift = f"""
        SELECT h.geography, YEAR(h.date) as yr, QUARTER(h.date) as qtr,
               ROUND(AVG(h.pct_nav), 2) as avg_allocation_pct
        FROM {HOLDINGS_TABLE} h {join_clause}
        {where_sql}
        GROUP BY h.geography, YEAR(h.date), QUARTER(h.date)
        ORDER BY yr DESC, qtr DESC
        """
        by_geo = _execute_query(geo_shift)

        return json.dumps({
            "sector_shifts": by_sector.get("rows", []),
            "geo_shifts": by_geo.get("rows", []),
            "strategy_filter": strategy
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def check_portfolio_kpis() -> str:
    """Check portfolio KPIs against performance thresholds.

    Monitors:
    - weighted_avg_return vs benchmark (target: positive spread)
    - concentration_top5_pct (threshold: 40%)
    - total_aum trends
    - manager_count by segment
    """
    try:
        query = f"""
        SELECT date, portfolio_segment, total_aum, weighted_avg_return,
               concentration_top5_pct, benchmark_spread, manager_count
        FROM {KPI_TABLE}
        ORDER BY date DESC LIMIT 50
        """
        result = _execute_query(query)
        rows = result.get("rows", [])
        if not rows:
            return json.dumps({"status": "no_data", "message": "No KPI data available"})

        alerts = []
        latest = rows[0]

        conc = float(latest.get("concentration_top5_pct", 0) or 0)
        if conc > 40:
            alerts.append({"metric": "concentration_top5_pct", "value": conc, "threshold": 40, "status": "breach"})
        elif conc > 35:
            alerts.append({"metric": "concentration_top5_pct", "value": conc, "threshold": 40, "status": "warning"})

        spread = float(latest.get("benchmark_spread", 0) or 0)
        if spread < -0.01:
            alerts.append({"metric": "benchmark_spread", "value": round(spread * 100, 2), "threshold": 0, "status": "breach"})
        elif spread < 0:
            alerts.append({"metric": "benchmark_spread", "value": round(spread * 100, 2), "threshold": 0, "status": "warning"})

        wav_ret = float(latest.get("weighted_avg_return", 0) or 0)

        return json.dumps({
            "latest_date": latest.get("date"),
            "metrics": {
                "weighted_avg_return_pct": round(wav_ret * 100, 3),
                "concentration_top5_pct": conc,
                "benchmark_spread_pct": round(spread * 100, 3),
                "total_aum": latest.get("total_aum"),
            },
            "alerts": alerts,
            "overall_status": "breach" if any(a["status"] == "breach" for a in alerts) else "warning" if alerts else "compliant"
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def write_analysis(
    analysis_type: str, insights: str, recommendations: Optional[str] = None,
    encounter_id: Optional[str] = None, agent_mode: str = "rag", priority: Optional[str] = None,
) -> str:
    """Write analysis results to the analysis_outputs table.

    Analysis types: performance_monitoring, concentration_analysis, flow_analysis,
    exposure_analysis, investment_action_report, portfolio_readiness, policy_compliance

    Priority levels: critical, high, medium, low
    """
    try:
        record_id = str(uuid.uuid4())
        created_at = datetime.utcnow()

        lakebase_success = False
        try:
            from src.db import session_scope
            from src.models.analysis import AnalysisOutput
            with session_scope() as session:
                analysis = AnalysisOutput(
                    id=record_id, encounter_id=encounter_id, analysis_type=analysis_type,
                    insights=insights, recommendations=recommendations, created_at=created_at,
                    agent_mode=agent_mode, status='pending', priority=priority
                )
                session.add(analysis)
                session.commit()
                lakebase_success = True
        except Exception as lb_error:
            logger.warning(f"write_analysis: Lakebase failed, falling back to Unity Catalog: {lb_error}")

        if not lakebase_success:
            def escape(s):
                return s.replace("'", "''") if s else None
            insights_escaped = escape(insights)
            reco_escaped = escape(recommendations) if recommendations else None
            enc_escaped = escape(encounter_id) if encounter_id else None
            priority_escaped = escape(priority) if priority else None
            reco_value = f"'{reco_escaped}'" if reco_escaped else "NULL"
            enc_value = f"'{enc_escaped}'" if enc_escaped else "NULL"
            priority_value = f"'{priority_escaped}'" if priority_escaped else "NULL"

            insert_sql = f"""
            INSERT INTO {ANALYSIS_TABLE}
            (id, encounter_id, analysis_type, insights, recommendations, created_at, agent_mode, metadata, status, priority)
            VALUES ('{record_id}', {enc_value}, '{escape(analysis_type)}', '{insights_escaped}',
                    {reco_value}, '{created_at.isoformat()}', '{escape(agent_mode)}', NULL, 'pending', {priority_value})
            """
            result = _execute_query(insert_sql)
            if not (result.get("success", False) or result.get("error") is None):
                return json.dumps({"error": f"Write failed: {result.get('error')}"})

        return json.dumps({
            "success": True, "id": record_id, "analysis_type": analysis_type,
            "storage": "lakebase" if lakebase_success else "unity_catalog",
            "message": "Analysis saved successfully"
        })
    except Exception as e:
        logger.error(f"write_analysis error: {e}")
        return json.dumps({"error": str(e)})


@tool
def search_investment_policies(query: str, num_results: int = 3) -> str:
    """Search investment policies, IPS guidelines, and compliance procedures.

    Use this when:
    - Asked about investment policy or allocation guidelines
    - Need guidance on due diligence, liquidity, or compliance procedures
    - Looking for concentration limits, rebalancing triggers, or watchlist criteria
    - Need step-by-step protocols for investment operations
    """
    logger.info(f"search_investment_policies called with query: {query}")
    num_results = min(max(num_results, 1), 10)
    try:
        w = get_workspace_client()
        resp = w.vector_search_indexes.query_index(
            index_name=SOP_VECTOR_INDEX,
            query_text=query,
            columns=["chunk_id", "chunk_text", "source_doc", "section_title"],
            num_results=num_results,
        )
        data_array = resp.result.data_array if resp.result else []
        matches = []
        for row in (data_array or []):
            if len(row) >= 2:
                matches.append({
                    "score": row[0] if row[0] else None,
                    "chunk_id": row[1] if len(row) > 1 else None,
                    "content": row[2] if len(row) > 2 else None,
                    "source_doc": row[3] if len(row) > 3 else None,
                    "section": row[4] if len(row) > 4 else None,
                })
        if not matches:
            return json.dumps({"matches": [], "query": query, "message": "No policy documents found. The investment policy vector index may not be set up yet."})
        return json.dumps({"matches": matches, "query": query})
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
            return json.dumps({"error": "Investment policy vector index not available. Please run the policy setup notebook.", "query": query})
        return json.dumps({"error": error_msg, "query": query})


@tool
def check_data_freshness() -> str:
    """Check if data pipelines are current by examining latest timestamps in key tables."""
    try:
        tables_to_check = [
            {"table": FUNDS_TABLE, "ts_col": "inception_date", "name": "Fund Data"},
            {"table": PERFORMANCE_TABLE, "ts_col": "date", "name": "Performance Data"},
            {"table": FLOWS_TABLE, "ts_col": "date", "name": "Flow Data"},
            {"table": KPI_TABLE, "ts_col": "date", "name": "Portfolio KPIs"},
        ]
        freshness_results = []
        overall_status = "fresh"
        stale_tables = []

        for table_info in tables_to_check:
            query = f"""
            SELECT MAX({table_info['ts_col']}) as latest_ts, COUNT(*) as row_count,
                   TIMESTAMPDIFF(HOUR, MAX({table_info['ts_col']}), CURRENT_TIMESTAMP) as hours_since_update
            FROM {table_info['table']}
            """
            result = _execute_query(query)
            if result["success"] and result["rows"]:
                row = result["rows"][0]
                hours_since = float(row.get("hours_since_update", 999) or 999)
                if hours_since > 48:
                    status = "critical"
                    overall_status = "critical"
                    stale_tables.append(table_info["name"])
                elif hours_since > 24:
                    status = "warning"
                    if overall_status != "critical":
                        overall_status = "warning"
                    stale_tables.append(table_info["name"])
                else:
                    status = "fresh"
                freshness_results.append({
                    "table": table_info["name"], "latest_timestamp": str(row.get("latest_ts")),
                    "hours_since_update": round(hours_since, 1), "row_count": row.get("row_count"), "status": status
                })

        recommendations = []
        if overall_status == "critical":
            recommendations.append(f"URGENT: Data pipeline >48h stale. Tables: {', '.join(stale_tables)}")
        elif overall_status == "warning":
            recommendations.append(f"Data pipeline delayed. Tables: {', '.join(stale_tables)}")
        else:
            recommendations.append("All data pipelines are current.")

        return json.dumps({"overall_status": overall_status, "tables": freshness_results,
                           "recommendations": recommendations, "checked_at": datetime.utcnow().isoformat()})
    except Exception as e:
        return json.dumps({"error": str(e)})


# Tool collections for different modes
QUICK_TOOLS = [execute_sql, search_fund_documents, search_investment_policies, analyze_performance_drivers, check_portfolio_kpis, check_data_freshness]
DEEP_TOOLS = [execute_sql, search_fund_documents, search_investment_policies, analyze_performance_drivers, analyze_concentration,
              check_fund_flows, check_exposure_shifts, check_portfolio_kpis, check_data_freshness, write_analysis]
ALL_TOOLS = {
    "execute_sql": execute_sql, "search_fund_documents": search_fund_documents,
    "search_investment_policies": search_investment_policies,
    "analyze_performance_drivers": analyze_performance_drivers, "analyze_concentration": analyze_concentration,
    "check_fund_flows": check_fund_flows, "check_exposure_shifts": check_exposure_shifts,
    "check_portfolio_kpis": check_portfolio_kpis, "check_data_freshness": check_data_freshness,
    "write_analysis": write_analysis,
}
