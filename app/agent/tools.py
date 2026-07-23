"""Agent tools for SQL execution, vector search, and hospital operations analysis."""
import os
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
    ENCOUNTERS_TABLE, DRUG_COSTS_TABLE, STAFFING_TABLE,
    ED_WAIT_TABLE, KPI_TABLE, ANALYSIS_TABLE,
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
    "dim_encounters", "fact_drug_costs", "fact_staffing",
    "fact_ed_wait_times", "fact_operational_kpis", "hospital_overview", "analysis_outputs",
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
    """Execute read-only SQL query against hospital operations data.

    Available tables:
    - dim_encounters: Patient encounters (encounter_id, patient_id, hospital, department, admit_date, discharge_date, los_days, discharge_day_of_week, payer, drg_code, attending_physician, is_readmission)
    - fact_drug_costs: Drug costs (encounter_id, date, hospital, department, drug_name, drug_category, unit_cost, quantity, total_cost)
    - fact_staffing: Staffing data (date, hospital, department, staff_type, fte_count, cost_per_fte, total_cost)
    - fact_ed_wait_times: ED wait times (encounter_id, hospital, arrival_time, triage_time, provider_seen_time, disposition_time, wait_minutes, acuity_level)
    - fact_operational_kpis: Daily KPIs (date, hospital, department, avg_los, avg_ed_wait_minutes, bed_utilization_pct, contract_labor_pct, drug_cost_per_encounter, readmission_rate)
    - hospital_overview: Summary VIEW (hospital, total_encounters, avg_los, readmission_rate_pct, department_count, physician_count)
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
def search_encounters(query: str, num_results: int = 5) -> str:
    """Search patient encounters using semantic similarity.

    Use natural language to describe what you're looking for:
    - "encounters with high LOS in cardiology"
    - "readmissions at Hospital A in November"
    - "emergency department visits with long wait times"
    """
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
def analyze_cost_drivers(hospital: Optional[str] = None, month: Optional[int] = None) -> str:
    """Analyze drug cost drivers by hospital and time period.

    Identifies:
    - Top drug categories by total spend
    - Cost trends over time
    - Anomalous cost spikes
    - Comparison across hospitals
    """
    try:
        _validate_identifier(hospital, "hospital")
        if month is not None and not (1 <= month <= 12):
            return json.dumps({"error": "month must be between 1 and 12"})
        where_clauses = []
        if hospital:
            where_clauses.append(f"hospital = '{hospital}'")
        if month:
            where_clauses.append(f"MONTH(date) = {month}")
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Top drugs by cost
        top_drugs_query = f"""
        SELECT drug_category, drug_name, SUM(total_cost) as total_spend,
               COUNT(*) as order_count, AVG(unit_cost) as avg_unit_cost
        FROM {DRUG_COSTS_TABLE} {where_sql}
        GROUP BY drug_category, drug_name
        ORDER BY total_spend DESC LIMIT 15
        """
        top_drugs = _execute_query(top_drugs_query)

        # Monthly trend
        trend_query = f"""
        SELECT MONTH(date) as month, hospital, SUM(total_cost) as monthly_spend,
               COUNT(DISTINCT encounter_id) as encounter_count,
               SUM(total_cost) / COUNT(DISTINCT encounter_id) as cost_per_encounter
        FROM {DRUG_COSTS_TABLE} {where_sql}
        GROUP BY MONTH(date), hospital ORDER BY month
        """
        trend = _execute_query(trend_query)

        return json.dumps({
            "top_drugs": top_drugs.get("rows", []),
            "monthly_trend": trend.get("rows", []),
            "filters": {"hospital": hospital, "month": month}
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def analyze_los_factors(hospital: Optional[str] = None) -> str:
    """Analyze length of stay drivers and patterns.

    Examines:
    - LOS by hospital, department, day of week
    - Discharge day patterns (Monday effect)
    - Relationship between LOS and readmission
    - Payer mix impact on LOS
    """
    try:
        _validate_identifier(hospital, "hospital")
        where_sql = f"WHERE hospital = '{hospital}'" if hospital else ""

        # LOS by hospital and department
        dept_query = f"""
        SELECT hospital, department, ROUND(AVG(los_days), 1) as avg_los,
               COUNT(*) as encounter_count,
               ROUND(SUM(CASE WHEN is_readmission THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as readmit_pct
        FROM {ENCOUNTERS_TABLE} {where_sql}
        GROUP BY hospital, department ORDER BY avg_los DESC
        """
        by_dept = _execute_query(dept_query)

        # LOS by discharge day of week
        dow_query = f"""
        SELECT discharge_day_of_week, ROUND(AVG(los_days), 1) as avg_los,
               COUNT(*) as encounter_count
        FROM {ENCOUNTERS_TABLE} {where_sql}
        GROUP BY discharge_day_of_week ORDER BY avg_los DESC
        """
        by_dow = _execute_query(dow_query)

        # LOS by payer
        payer_query = f"""
        SELECT payer, ROUND(AVG(los_days), 1) as avg_los, COUNT(*) as encounter_count
        FROM {ENCOUNTERS_TABLE} {where_sql}
        GROUP BY payer ORDER BY avg_los DESC
        """
        by_payer = _execute_query(payer_query)

        return json.dumps({
            "by_department": by_dept.get("rows", []),
            "by_discharge_day": by_dow.get("rows", []),
            "by_payer": by_payer.get("rows", []),
            "hospital_filter": hospital
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def check_ed_performance(hospital: Optional[str] = None) -> str:
    """Check Emergency Department performance metrics.

    Analyzes:
    - Wait times by acuity level
    - Threshold breaches (>60 min for acuity 3-5, >15 min for acuity 1-2)
    - Trends over time
    - Hospital comparison
    """
    try:
        _validate_identifier(hospital, "hospital")
        where_sql = f"WHERE hospital = '{hospital}'" if hospital else ""

        # Wait times by acuity
        acuity_query = f"""
        SELECT acuity_level, ROUND(AVG(wait_minutes), 1) as avg_wait,
               ROUND(PERCENTILE_APPROX(wait_minutes, 0.9), 1) as p90_wait,
               COUNT(*) as visit_count,
               SUM(CASE WHEN (acuity_level <= 2 AND wait_minutes > 15)
                        OR (acuity_level > 2 AND wait_minutes > 60) THEN 1 ELSE 0 END) as threshold_breaches
        FROM {ED_WAIT_TABLE} {where_sql}
        GROUP BY acuity_level ORDER BY acuity_level
        """
        by_acuity = _execute_query(acuity_query)

        # By hospital
        hospital_query = f"""
        SELECT hospital, ROUND(AVG(wait_minutes), 1) as avg_wait,
               COUNT(*) as visit_count
        FROM {ED_WAIT_TABLE} {where_sql}
        GROUP BY hospital
        """
        by_hospital = _execute_query(hospital_query)

        return json.dumps({
            "by_acuity": by_acuity.get("rows", []),
            "by_hospital": by_hospital.get("rows", []),
            "thresholds": {"acuity_1_2": "15 min", "acuity_3_5": "60 min"}
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def check_staffing_efficiency(hospital: Optional[str] = None, department: Optional[str] = None) -> str:
    """Analyze staffing efficiency and contract labor usage.

    Examines:
    - Contract labor percentage by department
    - Cost comparison: full-time vs contract vs per-diem
    - Departments with highest contract labor reliance
    - Trends over time
    """
    try:
        _validate_identifier(hospital, "hospital")
        _validate_identifier(department, "department")
        where_clauses = []
        if hospital:
            where_clauses.append(f"hospital = '{hospital}'")
        if department:
            where_clauses.append(f"department = '{department}'")
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Contract labor % by department
        dept_query = f"""
        SELECT hospital, department,
               ROUND(SUM(CASE WHEN staff_type = 'contract' THEN fte_count ELSE 0 END)
                     / SUM(fte_count) * 100, 1) as contract_labor_pct,
               SUM(total_cost) as total_staffing_cost,
               SUM(CASE WHEN staff_type = 'contract' THEN total_cost ELSE 0 END) as contract_cost
        FROM {STAFFING_TABLE} {where_sql}
        GROUP BY hospital, department
        ORDER BY contract_labor_pct DESC
        """
        by_dept = _execute_query(dept_query)

        # Cost by staff type
        type_query = f"""
        SELECT staff_type, ROUND(AVG(cost_per_fte), 2) as avg_cost_per_fte,
               SUM(total_cost) as total_cost, SUM(fte_count) as total_fte
        FROM {STAFFING_TABLE} {where_sql}
        GROUP BY staff_type
        """
        by_type = _execute_query(type_query)

        return json.dumps({
            "by_department": by_dept.get("rows", []),
            "by_staff_type": by_type.get("rows", []),
            "filters": {"hospital": hospital, "department": department}
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def check_operational_kpis() -> str:
    """Check operational KPIs against performance thresholds.

    Monitors:
    - avg_los (threshold: 5.0 days)
    - avg_ed_wait_minutes (threshold: 60 min)
    - bed_utilization_pct (threshold: 85%)
    - contract_labor_pct (threshold: 25%)
    - readmission_rate (threshold: 10%)
    """
    try:
        query = f"""
        SELECT date, hospital, department, avg_los, avg_ed_wait_minutes,
               bed_utilization_pct, contract_labor_pct, drug_cost_per_encounter, readmission_rate
        FROM {KPI_TABLE}
        ORDER BY date DESC LIMIT 50
        """
        result = _execute_query(query)
        rows = result.get("rows", [])
        if not rows:
            return json.dumps({"status": "no_data", "message": "No KPI data available"})

        alerts = []
        latest = rows[0]

        los = float(latest.get("avg_los", 0) or 0)
        if los > 5.0:
            alerts.append({"metric": "avg_los", "value": los, "threshold": 5.0, "status": "breach"})
        elif los > 4.5:
            alerts.append({"metric": "avg_los", "value": los, "threshold": 5.0, "status": "warning"})

        ed_wait = float(latest.get("avg_ed_wait_minutes", 0) or 0)
        if ed_wait > 60:
            alerts.append({"metric": "ed_wait_minutes", "value": ed_wait, "threshold": 60, "status": "breach"})

        contract = float(latest.get("contract_labor_pct", 0) or 0)
        if contract > 25:
            alerts.append({"metric": "contract_labor_pct", "value": contract, "threshold": 25, "status": "breach"})

        readmit = float(latest.get("readmission_rate", 0) or 0)
        if readmit > 10:
            alerts.append({"metric": "readmission_rate", "value": readmit, "threshold": 10, "status": "breach"})

        return json.dumps({
            "latest_date": latest.get("date"),
            "metrics": {
                "avg_los": los, "avg_ed_wait_minutes": ed_wait,
                "contract_labor_pct": contract, "readmission_rate": readmit,
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

    Analysis types: cost_monitoring, los_analysis, ed_performance, staffing_analysis,
    next_best_action_report, compliance_monitoring, strategy_optimization, learning_reflection

    Priority levels: critical, high, medium, low
    """
    try:
        record_id = str(uuid.uuid4())
        created_at = datetime.utcnow()

        # Optionally try Lakebase first (opt-in via USE_LAKEBASE). Off by default:
        # the app syncs only app/, so `src.db` isn't importable at runtime and this
        # branch would throw on every write. Unity Catalog is the default store.
        lakebase_success = False
        if os.environ.get("USE_LAKEBASE", "false").lower() == "true":
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
            from databricks.sdk.service.sql import StatementParameterListItem
            w = get_workspace_client()
            insert_sql = f"""
            INSERT INTO {ANALYSIS_TABLE}
            (id, encounter_id, analysis_type, insights, recommendations, created_at, agent_mode, metadata, status, priority)
            VALUES (:p_id, :p_encounter_id, :p_analysis_type, :p_insights,
                    :p_recommendations, :p_created_at, :p_agent_mode, NULL, 'pending', :p_priority)
            """
            params = [
                StatementParameterListItem(name="p_id", value=record_id),
                StatementParameterListItem(name="p_encounter_id", value=encounter_id),
                StatementParameterListItem(name="p_analysis_type", value=analysis_type),
                StatementParameterListItem(name="p_insights", value=insights),
                StatementParameterListItem(name="p_recommendations", value=recommendations),
                StatementParameterListItem(name="p_created_at", value=created_at.isoformat()),
                StatementParameterListItem(name="p_agent_mode", value=agent_mode),
                StatementParameterListItem(name="p_priority", value=priority),
            ]
            result = w.statement_execution.execute_statement(
                warehouse_id=WAREHOUSE_ID, statement=insert_sql,
                parameters=params, wait_timeout="30s",
            )
            state = result.status.state.value if result.status and result.status.state else "UNKNOWN"
            if state not in ("SUCCEEDED", "CLOSED"):
                return json.dumps({"error": f"Write failed: {result.status.error}"})

        return json.dumps({
            "success": True, "id": record_id, "analysis_type": analysis_type,
            "storage": "lakebase" if lakebase_success else "unity_catalog",
            "message": "Analysis saved successfully"
        })
    except Exception as e:
        logger.error(f"write_analysis error: {e}")
        return json.dumps({"error": str(e)})


@tool
def search_sops(query: str, num_results: int = 3) -> str:
    """Search Standard Operating Procedures and hospital policies for guidance.

    Use this when:
    - Asked about "next best action" or recommended procedures
    - Need guidance on handling operational issues (high LOS, staffing, ED flow)
    - Looking for regulatory compliance or accreditation procedures
    - Need step-by-step protocols for hospital operations
    """
    logger.info(f"search_sops called with query: {query}")
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
            return json.dumps({"matches": [], "query": query, "message": "No SOP documents found. The SOP vector index may not be set up yet."})
        return json.dumps({"matches": matches, "query": query})
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
            return json.dumps({"error": "SOP vector index not available. Please run the SOP setup notebook.", "query": query})
        return json.dumps({"error": error_msg, "query": query})


@tool
def check_data_freshness() -> str:
    """Check if data pipelines are current by examining latest timestamps in key tables."""
    try:
        tables_to_check = [
            {"table": ENCOUNTERS_TABLE, "ts_col": "admit_date", "name": "Encounter Data"},
            {"table": DRUG_COSTS_TABLE, "ts_col": "date", "name": "Drug Costs"},
            {"table": STAFFING_TABLE, "ts_col": "date", "name": "Staffing Data"},
            {"table": KPI_TABLE, "ts_col": "date", "name": "Operational KPIs"},
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
QUICK_TOOLS = [execute_sql, search_encounters, search_sops, analyze_cost_drivers, check_operational_kpis, check_data_freshness]
DEEP_TOOLS = [execute_sql, search_encounters, search_sops, analyze_cost_drivers, analyze_los_factors,
              check_ed_performance, check_staffing_efficiency, check_operational_kpis, check_data_freshness, write_analysis]
ALL_TOOLS = {
    "execute_sql": execute_sql, "search_encounters": search_encounters, "search_sops": search_sops,
    "analyze_cost_drivers": analyze_cost_drivers, "analyze_los_factors": analyze_los_factors,
    "check_ed_performance": check_ed_performance, "check_staffing_efficiency": check_staffing_efficiency,
    "check_operational_kpis": check_operational_kpis, "check_data_freshness": check_data_freshness,
    "write_analysis": write_analysis,
}
