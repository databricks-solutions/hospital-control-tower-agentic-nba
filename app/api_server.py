"""Flask server for Investment Portfolio Intelligence App."""
import os
import re
import json
import time
import uuid
import queue
import logging
import functools
import threading
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from databricks.sdk.service.sql import Format, Disposition

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
VALID_ANALYSIS_TYPES = {
    "performance_monitoring", "concentration_analysis", "flow_analysis", "exposure_analysis",
    "investment_action_report", "portfolio_readiness", "policy_compliance",
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DIST_FOLDER = os.path.join(os.path.dirname(__file__), "dist")
if not os.path.exists(DIST_FOLDER):
    os.makedirs(DIST_FOLDER)
    with open(os.path.join(DIST_FOLDER, "index.html"), "w") as f:
        f.write("<html><body><h1>Building...</h1><p>React app is building. Refresh in a moment.</p></body></html>")

app = Flask(__name__, static_folder="dist", static_url_path="")
CORS(app)


@app.errorhandler(Exception)
def handle_exception(e):
    code = getattr(e, "code", 500)
    logger.error(f"Unhandled error: {e}", exc_info=True)
    return jsonify({"error": "Internal server error"}), code


from agent.config import (
    CATALOG, SCHEMA, WAREHOUSE_ID,
    ANALYSIS_TABLE, FUNDS_TABLE, PERFORMANCE_TABLE, HOLDINGS_TABLE,
    FLOWS_TABLE, KPI_TABLE, PORTFOLIO_OVERVIEW_TABLE,
    get_workspace_client, validate_config,
)

DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"

def require_demo_mode(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not DEMO_MODE:
            return jsonify({"error": "Data mutation disabled (DEMO_MODE=false)"}), 403
        return f(*args, **kwargs)
    return wrapper

_agent_loaded = False
_invoke_agent = None
_invoke_deep_streaming = None
_get_autonomous = None
_start_autonomous = None

_health_score_history = []
_autonomous_latest_result = {"timestamp": None, "message": None, "issues_found": None}
_deep_tasks = {}  # task_id -> {"status","stage","response","tool_calls","routing_trace","error","created"}

validate_config()
logger.info("=" * 60)
logger.info("STARTUP CONFIG:")
logger.info(f"  CATALOG       = {CATALOG!r}")
logger.info(f"  SCHEMA        = {SCHEMA!r}")
logger.info(f"  WAREHOUSE_ID  = {WAREHOUSE_ID!r}")
logger.info(f"  FUNDS        = {FUNDS_TABLE!r}")
logger.info(f"  PERFORMANCE  = {PERFORMANCE_TABLE!r}")
logger.info(f"  HOLDINGS     = {HOLDINGS_TABLE!r}")
logger.info(f"  FLOWS        = {FLOWS_TABLE!r}")
logger.info(f"  KPI          = {KPI_TABLE!r}")
logger.info(f"  ANALYSIS     = {ANALYSIS_TABLE!r}")
if not WAREHOUSE_ID:
    logger.error("WAREHOUSE_ID is EMPTY -- all SQL queries will fail!")
logger.info("=" * 60)


# ---------------------------------------------------------------------------
# SQL helpers -- force JSON_ARRAY format so data_array is always populated
# ---------------------------------------------------------------------------

def _run_sql(query, w=None):
    """Execute a SELECT query and return (columns, rows). Always uses JSON_ARRAY + INLINE."""
    if not w:
        w = get_workspace_client()
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=query,
        wait_timeout="30s",
        format=Format.JSON_ARRAY,
        disposition=Disposition.INLINE,
    )
    state = r.status.state.value if r.status and r.status.state else "UNKNOWN"
    if state not in ("SUCCEEDED", "CLOSED"):
        err = r.status.error if r.status else None
        logger.warning(f"SQL state={state}, error={err}, query={query[:120]}")
        return [], []
    if r.result and r.result.data_array:
        cols = [c.name for c in r.manifest.schema.columns]
        return cols, r.result.data_array
    return [], []


def _exec_sql(query, w=None):
    """Execute a write SQL statement (INSERT/UPDATE/DDL). Raises on failure."""
    if not w:
        w = get_workspace_client()
    r = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=query,
        wait_timeout="30s",
    )
    state = r.status.state.value if r.status and r.status.state else "UNKNOWN"
    if state not in ("SUCCEEDED", "CLOSED"):
        raise RuntimeError(f"SQL failed (state={state}): {r.status.error}")


# ---------------------------------------------------------------------------
# Startup initialization
# ---------------------------------------------------------------------------

def _ensure_analysis_table():
    """Create analysis_outputs table if it doesn't exist."""
    if not WAREHOUSE_ID or not CATALOG:
        return
    try:
        ddl = f"""CREATE TABLE IF NOT EXISTS {ANALYSIS_TABLE} (
            id STRING COMMENT 'Unique analysis ID',
            encounter_id STRING COMMENT 'Related fund_id or entity ID',
            analysis_type STRING COMMENT 'Type of analysis',
            insights STRING COMMENT 'Main findings',
            recommendations STRING COMMENT 'Actionable recommendations',
            created_at TIMESTAMP COMMENT 'When created',
            agent_mode STRING COMMENT 'quick or deep',
            metadata MAP<STRING, STRING> COMMENT 'Additional metadata',
            priority STRING COMMENT 'critical/high/medium/low',
            status STRING COMMENT 'pending/approved/rejected',
            reviewed_by STRING COMMENT 'Who reviewed',
            reviewed_at TIMESTAMP COMMENT 'When reviewed',
            engineer_notes STRING COMMENT 'Reviewer notes'
        ) USING DELTA"""
        _exec_sql(ddl)
        logger.info(f"INIT: analysis_outputs table ensured at {ANALYSIS_TABLE}")
    except Exception as e:
        logger.warning(f"INIT: Could not ensure analysis_outputs table: {e}")


def _shift_data_dates_if_stale():
    """If the most recent performance data is older than 7 days, shift ALL table dates forward so data stays fresh."""
    if not WAREHOUSE_ID or not CATALOG:
        return
    try:
        cols, rows = _run_sql(f"SELECT DATEDIFF(CURRENT_DATE, MAX(DATE(date))) as stale_days FROM {PERFORMANCE_TABLE}")
        if not rows or not rows[0] or rows[0][0] is None:
            logger.info("SEED: No performance data found, skipping date shift")
            return
        stale_days = int(rows[0][0])
        if stale_days <= 3:
            logger.info(f"SEED: Data is fresh (most recent performance {stale_days} days ago)")
            return
        shift = stale_days - 1
        logger.info(f"SEED: Data is {stale_days} days stale -- shifting all dates forward by {shift} days")
        _exec_sql(f"UPDATE {PERFORMANCE_TABLE} SET date = date + INTERVAL {shift} DAYS")
        _exec_sql(f"UPDATE {FLOWS_TABLE} SET date = date + INTERVAL {shift} DAYS")
        _exec_sql(f"UPDATE {HOLDINGS_TABLE} SET date = date + INTERVAL {shift} DAYS")
        _exec_sql(f"UPDATE {KPI_TABLE} SET date = date + INTERVAL {shift} DAYS")
        logger.info(f"SEED: Shifted all table dates forward by {shift} days")
    except Exception as e:
        logger.warning(f"SEED: Date shift failed (non-fatal): {e}")


def _seed_baseline_if_needed():
    """On startup, seed baseline demo data across all tables if no recent data exists."""
    if not WAREHOUSE_ID or not CATALOG:
        logger.warning("SEED: Skipping -- WAREHOUSE_ID or CATALOG not configured")
        return
    try:
        import random

        _shift_data_dates_if_stale()

        cols, rows = _run_sql(
            f"SELECT COUNT(*) FROM {FUNDS_TABLE} WHERE fund_id LIKE 'FUND_%'"
        )
        count = int(rows[0][0] or 0) if rows else 0

        if count >= 20:
            logger.info(f"SEED: {count} seeded funds found, skipping seed")
            return

        logger.info("SEED: No recent fund data -- seeding baseline demo data")
        now = datetime.utcnow()
        ts = int(now.timestamp())
        strategies = ["Public Equity", "Private Credit", "Venture Capital", "Real Assets", "Hedge Fund"]
        managers = ["Blackstone Partners", "KKR Capital", "Apollo Management", "Carlyle Group", "Ares Management",
                    "TPG Capital", "Warburg Pincus", "General Atlantic", "Silver Lake", "Thoma Bravo",
                    "Vista Equity", "Hellman & Friedman", "Advent International", "EQT Partners", "Permira"]
        domiciles = ["Delaware", "Cayman Islands", "Luxembourg", "Ireland"]
        sectors = ["Technology", "Healthcare", "Financials", "Energy", "Consumer", "Industrials"]
        geographies = ["North America", "Europe", "Asia Pacific", "Emerging Markets"]
        liquidity_terms = ["Monthly", "Quarterly", "Annual", "Locked"]

        fund_rows, perf_rows, hold_rows, flow_rows, kpi_rows = [], [], [], [], []

        num_funds = random.randint(30, 50)
        for i in range(num_funds):
            fid = f"FUND_{ts}_{i:03d}"
            strategy = random.choice(strategies)
            manager = random.choice(managers)
            fund_name = f"{manager} {strategy.replace(' ', '')} Fund {2020 + (i % 4)}"
            vintage = 2019 + random.randint(0, 5)
            aum = round(random.uniform(50, 2500), 1)
            commitment = round(aum * random.uniform(1.0, 1.5), 1)
            status = "active" if random.random() < 0.9 else "watchlist"
            domicile = random.choice(domiciles)
            inception = (now - timedelta(days=365 * (2025 - vintage))).strftime("%Y-%m-%d 00:00:00")
            fund_rows.append(
                f"('{fid}', '{fund_name}', '{manager}', '{strategy}', {vintage}, {aum}, {commitment}, "
                f"'{status}', '{domicile}', TIMESTAMP'{inception}')"
            )

            for month_ago in range(12):
                pdate = (now - timedelta(days=30 * month_ago)).strftime("%Y-%m-%d 00:00:00")
                monthly_ret = round(random.uniform(-0.03, 0.05), 4)
                bench_ret = round(random.uniform(-0.02, 0.03), 4)
                alpha_val = round(monthly_ret - bench_ret, 4)
                nav = round(aum * (1 + random.uniform(-0.1, 0.2)), 1)
                ytd = round(random.uniform(-0.05, 0.15), 4)
                itd = round(random.uniform(0.05, 0.35), 4)
                perf_rows.append(
                    f"('{fid}', TIMESTAMP'{pdate}', {nav}, {monthly_ret}, {ytd}, {itd}, {bench_ret}, {alpha_val})"
                )

            for pos_idx in range(random.randint(3, 8)):
                pdate = (now - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d 00:00:00")
                pos_name = f"Position_{fid}_{pos_idx}"
                sector = random.choice(sectors)
                geo = random.choice(geographies)
                pct_nav = round(random.uniform(2, 25), 2)
                mv = round(aum * pct_nav / 100, 1)
                chg = round(random.uniform(-0.05, 0.08), 4)
                hold_rows.append(
                    f"('{fid}', TIMESTAMP'{pdate}', '{pos_name}', '{sector}', '{geo}', {pct_nav}, {mv}, {chg})"
                )

            for flow_idx in range(random.randint(2, 6)):
                fdate = (now - timedelta(days=random.randint(0, 90))).strftime("%Y-%m-%d 00:00:00")
                calls = round(random.uniform(0, 50), 1)
                dist = round(random.uniform(0, 80), 1)
                net = round(dist - calls, 1)
                rem = round(commitment * random.uniform(0.2, 0.8), 1)
                liq = random.choice(liquidity_terms)
                flow_rows.append(
                    f"('{fid}', TIMESTAMP'{fdate}', {calls}, {dist}, {net}, {rem}, '{liq}')"
                )

        for week in range(4):
            kdate = (now - timedelta(weeks=week)).strftime("%Y-%m-%d 00:00:00")
            for strategy in strategies:
                seg_aum = round(random.uniform(500, 5000), 1)
                wavg_ret = round(random.uniform(-0.01, 0.04), 4)
                conc = round(random.uniform(15, 45), 1)
                spread = round(random.uniform(-0.005, 0.02), 4)
                mgr_cnt = random.randint(3, 12)
                kpi_rows.append(
                    f"(TIMESTAMP'{kdate}', '{strategy}', {seg_aum}, {wavg_ret}, {conc}, {spread}, {mgr_cnt})"
                )

        stmts = []
        if fund_rows:
            stmts.append(
                f"INSERT INTO {FUNDS_TABLE} (fund_id, fund_name, manager_name, strategy, vintage_year, aum, commitment, status, domicile, inception_date) VALUES {', '.join(fund_rows)}"
            )
        if perf_rows:
            for chunk_start in range(0, len(perf_rows), 200):
                chunk = perf_rows[chunk_start:chunk_start + 200]
                stmts.append(
                    f"INSERT INTO {PERFORMANCE_TABLE} (fund_id, date, nav, monthly_return, ytd_return, itd_return, benchmark_return, alpha) VALUES {', '.join(chunk)}"
                )
        if hold_rows:
            for chunk_start in range(0, len(hold_rows), 200):
                chunk = hold_rows[chunk_start:chunk_start + 200]
                stmts.append(
                    f"INSERT INTO {HOLDINGS_TABLE} (fund_id, date, position_name, sector, geography, pct_nav, market_value, change_from_prior) VALUES {', '.join(chunk)}"
                )
        if flow_rows:
            for chunk_start in range(0, len(flow_rows), 200):
                chunk = flow_rows[chunk_start:chunk_start + 200]
                stmts.append(
                    f"INSERT INTO {FLOWS_TABLE} (fund_id, date, capital_calls, distributions, net_flow, commitment_remaining, liquidity_terms) VALUES {', '.join(chunk)}"
                )
        if kpi_rows:
            stmts.append(
                f"INSERT INTO {KPI_TABLE} (date, portfolio_segment, total_aum, weighted_avg_return, concentration_top5_pct, benchmark_spread, manager_count) VALUES {', '.join(kpi_rows)}"
            )

        for stmt in stmts:
            _exec_sql(stmt)

        logger.info(f"SEED: Inserted {len(fund_rows)} funds, {len(perf_rows)} performance, "
                    f"{len(hold_rows)} holdings, {len(flow_rows)} flows, {len(kpi_rows)} KPIs")
    except Exception as e:
        logger.warning(f"SEED: Failed to seed baseline data: {e}")


# Run startup initialization
_ensure_analysis_table()
_seed_baseline_if_needed()


def load_agent():
    global _agent_loaded, _invoke_agent, _invoke_deep_streaming, _get_autonomous, _start_autonomous
    if _agent_loaded:
        return True
    try:
        from agent.graph import invoke_agent, invoke_deep_agent_streaming
        from agent.autonomous import get_autonomous, start_autonomous
        _invoke_agent = invoke_agent
        _invoke_deep_streaming = invoke_deep_agent_streaming
        _get_autonomous = get_autonomous
        _start_autonomous = start_autonomous
        _agent_loaded = True
        logger.info("Agent module loaded successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to load agent module: {e}")
        return False


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react_app(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/health", methods=["GET"])
def health_check():
    status = {"status": "ok", "timestamp": datetime.utcnow().isoformat(), "agent_loaded": _agent_loaded}
    if _agent_loaded and _get_autonomous:
        try:
            status["autonomous"] = _get_autonomous().get_status()
        except Exception as e:
            status["autonomous_error"] = str(e)
    return jsonify(status)


@app.route("/api/config", methods=["GET"])
def get_config():
    from agent.graph import MLFLOW_ENABLED, MLFLOW_EXPERIMENT_ID
    host = os.environ.get("DATABRICKS_HOST", "")
    exp_url = None
    if host and MLFLOW_EXPERIMENT_ID:
        exp_url = f"{host.rstrip('/')}/ml/experiments/{MLFLOW_EXPERIMENT_ID}/traces"
    return jsonify({
        "catalog": CATALOG, "schema": SCHEMA,
        "warehouse_id": WAREHOUSE_ID[:8] + "..." if WAREHOUSE_ID else None,
        "mlflow_enabled": MLFLOW_ENABLED,
        "mlflow_experiment_url": exp_url,
    })


@app.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    if not load_agent():
        return jsonify({"error": "Agent not available"}), 503
    try:
        data = request.get_json()
        message = data.get("message", "")
        mode = data.get("mode", "orchestrator")
        history = data.get("history", [])
        stream = data.get("stream", False)
        if not message:
            return jsonify({"error": "No message provided"}), 400

        if stream and mode == "rag":
            return _start_deep_task(message, history)

        result = _invoke_agent(message=message, mode=mode, history=history)
        resp = {"response": result.get("response", ""), "tool_calls": result.get("tool_calls", []),
                "mode": result.get("mode", mode), "timestamp": datetime.utcnow().isoformat()}
        if result.get("intent"):
            resp["intent"] = result["intent"]
        return jsonify(resp)
    except Exception as e:
        logger.error(f"Agent chat error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _start_deep_task(message, history):
    """Submit deep analysis as a background task, return task_id for polling."""
    task_id = str(uuid.uuid4())[:12]
    _deep_tasks[task_id] = {"status": "running", "stage": "starting", "created": time.time()}

    progress_queue = _invoke_deep_streaming(message=message, history=history)

    def _monitor():
        try:
            while True:
                try:
                    event = progress_queue.get(timeout=300)
                except queue.Empty:
                    _deep_tasks[task_id] = {**_deep_tasks[task_id], "status": "error", "error": "Analysis timed out after 5 minutes."}
                    return
                if event.get("stage") == "done":
                    _deep_tasks[task_id] = {
                        "status": "done", "stage": "done",
                        "response": event.get("response", ""),
                        "tool_calls": event.get("tool_calls", []),
                        "routing_trace": event.get("routing_trace"),
                        "created": _deep_tasks[task_id]["created"],
                    }
                    return
                if event.get("stage") == "error":
                    _deep_tasks[task_id] = {**_deep_tasks[task_id], "status": "error", "error": event.get("message", "Unknown error")}
                    return
                _deep_tasks[task_id]["stage"] = event.get("stage", "running")
        except Exception as e:
            logger.error(f"Deep task monitor error: {e}", exc_info=True)
            _deep_tasks[task_id] = {**_deep_tasks[task_id], "status": "error", "error": str(e)}

    threading.Thread(target=_monitor, daemon=True).start()

    # Clean up tasks older than 10 minutes
    cutoff = time.time() - 600
    for tid in list(_deep_tasks):
        if _deep_tasks.get(tid, {}).get("created", 0) < cutoff:
            _deep_tasks.pop(tid, None)

    return jsonify({"task_id": task_id})


@app.route("/api/agent/task/<task_id>", methods=["GET"])
def get_deep_task(task_id):
    task = _deep_tasks.get(task_id)
    if not task:
        return jsonify({"status": "error", "error": "Task not found"}), 404
    return jsonify(task)


@app.route("/api/agent/plot", methods=["POST"])
def agent_plot():
    """Generate a chart specification from an agent response."""
    if not load_agent():
        return jsonify({"no_data": True, "reason": "Agent not available"}), 503
    try:
        body = request.json or {}
        content = body.get("content", "")
        history = body.get("history", [])
        if not content:
            return jsonify({"no_data": True, "reason": "No content provided"}), 400
        from agent.graph import create_plot_spec
        spec = create_plot_spec(content, history)
        return jsonify(spec)
    except Exception as e:
        logger.error(f"Plot agent error: {e}", exc_info=True)
        return jsonify({"no_data": True, "reason": str(e)}), 500


# Autonomous mode endpoints
@app.route("/api/autonomous/status", methods=["GET"])
def autonomous_status():
    if not load_agent():
        return jsonify({"error": "Agent not available", "is_running": False}), 200
    return jsonify(_get_autonomous().get_status())


@app.route("/api/autonomous/start", methods=["POST"])
def autonomous_start():
    if not load_agent():
        return jsonify({"error": "Agent not available"}), 503
    try:
        _start_autonomous()
        return jsonify({"success": True, "status": _get_autonomous().get_status()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/autonomous/stop", methods=["POST"])
def autonomous_stop():
    if not load_agent():
        return jsonify({"error": "Agent not available"}), 503
    try:
        _get_autonomous().stop()
        return jsonify({"success": True, "status": _get_autonomous().get_status()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/autonomous/config", methods=["PATCH"])
def autonomous_config():
    if not load_agent():
        return jsonify({"error": "Agent not available"}), 503
    try:
        data = request.get_json()
        autonomous = _get_autonomous()
        if "interval_seconds" in data:
            autonomous.set_interval(data["interval_seconds"])
        if "capabilities" in data:
            config = {c["id"]: c["enabled"] for c in data["capabilities"]}
            autonomous.set_capabilities(config)
        return jsonify({"success": True, "status": autonomous.get_status()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/autonomous/trigger", methods=["POST"])
def autonomous_trigger():
    if not load_agent():
        return jsonify({"error": "Agent not available"}), 503
    try:
        data = request.get_json() or {}
        capability = data.get("capability")
        result = _get_autonomous().trigger_now(capability)
        return jsonify({"success": True, "result": result, "status": _get_autonomous().get_status()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/autonomous/check-now", methods=["POST"])
def autonomous_check_now():
    """Trigger an immediate health check (and action report if issues found)."""
    if not load_agent():
        return jsonify({"error": "Agent not available"}), 503
    try:
        def _run_and_record():
            auto = _get_autonomous()
            auto._autonomous_job()
            last = auto.get_status()
            msg = last.get("last_result", "Check complete")
            issues = "issue" in str(msg).lower() or "breach" in str(msg).lower()
            record_autonomous_result(str(msg)[:200], issues)
        threading.Thread(target=_run_and_record, daemon=True).start()
        return jsonify({"success": True, "message": "Health check triggered"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/inject-anomaly", methods=["POST"])
@require_demo_mode
def inject_anomaly():
    """Insert anomalous investment data -- underperforming funds, concentration spikes, liquidity issues, negative alpha."""
    try:
        import random
        body = request.get_json(silent=True) or {}
        count = max(1, min(100, int(body.get("count", 10))))
        ts = int(datetime.utcnow().timestamp())
        now = datetime.utcnow()
        strategies = ["Public Equity", "Private Credit", "Venture Capital"]
        perf_rows, hold_rows, flow_rows, fund_rows = [], [], [], []

        for i in range(count):
            fid = f"ANOM_{ts}_{i:03d}"
            strategy = random.choice(strategies)
            aum = round(random.uniform(100, 800), 1)
            commitment = round(aum * 1.3, 1)
            fund_rows.append(
                f"('{fid}', 'Underperforming Fund {i}', 'Manager_ANOM_{i}', '{strategy}', 2021, {aum}, {commitment}, "
                f"'watchlist', 'Delaware', TIMESTAMP'2021-01-01 00:00:00')"
            )
            pdate = now.strftime("%Y-%m-%d 00:00:00")
            monthly_ret = round(random.uniform(-0.08, -0.02), 4)
            bench_ret = round(random.uniform(-0.01, 0.02), 4)
            alpha_val = round(monthly_ret - bench_ret, 4)
            perf_rows.append(
                f"('{fid}', TIMESTAMP'{pdate}', {aum * 0.9}, {monthly_ret}, -0.12, 0.02, {bench_ret}, {alpha_val})"
            )
            hold_rows.append(
                f"('{fid}', TIMESTAMP'{pdate}', 'Concentrated_Position', 'Technology', 'North America', "
                f"{round(random.uniform(35, 55), 1)}, {aum * 0.4}, -0.15)"
            )
            flow_rows.append(
                f"('{fid}', TIMESTAMP'{pdate}', {round(random.uniform(80, 150), 1)}, "
                f"{round(random.uniform(5, 20), 1)}, {round(random.uniform(-100, -50), 1)}, "
                f"{round(commitment * 0.6, 1)}, 'Locked')"
            )

        if fund_rows:
            _exec_sql(f"INSERT INTO {FUNDS_TABLE} (fund_id, fund_name, manager_name, strategy, vintage_year, aum, commitment, status, domicile, inception_date) VALUES {', '.join(fund_rows)}")
        if perf_rows:
            _exec_sql(f"INSERT INTO {PERFORMANCE_TABLE} (fund_id, date, nav, monthly_return, ytd_return, itd_return, benchmark_return, alpha) VALUES {', '.join(perf_rows)}")
        if hold_rows:
            _exec_sql(f"INSERT INTO {HOLDINGS_TABLE} (fund_id, date, position_name, sector, geography, pct_nav, market_value, change_from_prior) VALUES {', '.join(hold_rows)}")
        if flow_rows:
            _exec_sql(f"INSERT INTO {FLOWS_TABLE} (fund_id, date, capital_calls, distributions, net_flow, commitment_remaining, liquidity_terms) VALUES {', '.join(flow_rows)}")
        total = len(fund_rows) + len(perf_rows) + len(hold_rows) + len(flow_rows)
        return jsonify({"success": True, "injected": total, "funds": len(fund_rows)})
    except Exception as e:
        logger.error(f"Inject anomaly error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/inject-good", methods=["POST"])
@require_demo_mode
def inject_good_data():
    """Insert healthy fund performance data -- good returns, positive alpha, normal concentration."""
    try:
        import random
        body = request.get_json(silent=True) or {}
        count = max(1, min(100, int(body.get("count", 10))))
        ts = int(datetime.utcnow().timestamp())
        now = datetime.utcnow()
        strategies = ["Public Equity", "Private Credit", "Venture Capital", "Real Assets"]
        fund_rows, perf_rows, hold_rows, flow_rows = [], [], [], []

        for i in range(count):
            fid = f"GOOD_{ts}_{i:03d}"
            strategy = random.choice(strategies)
            aum = round(random.uniform(200, 1500), 1)
            commitment = round(aum * 1.1, 1)
            fund_rows.append(
                f"('{fid}', 'Strong Performer Fund {i}', 'Manager_GOOD_{i}', '{strategy}', 2022, {aum}, {commitment}, "
                f"'active', 'Delaware', TIMESTAMP'2022-01-01 00:00:00')"
            )
            pdate = now.strftime("%Y-%m-%d 00:00:00")
            monthly_ret = round(random.uniform(0.02, 0.06), 4)
            bench_ret = round(random.uniform(0.01, 0.03), 4)
            alpha_val = round(monthly_ret - bench_ret, 4)
            perf_rows.append(
                f"('{fid}', TIMESTAMP'{pdate}', {aum * 1.05}, {monthly_ret}, 0.08, 0.15, {bench_ret}, {alpha_val})"
            )
            hold_rows.append(
                f"('{fid}', TIMESTAMP'{pdate}', 'Diversified_Position', 'Technology', 'North America', "
                f"{round(random.uniform(5, 18), 1)}, {aum * 0.1}, 0.03)"
            )
            flow_rows.append(
                f"('{fid}', TIMESTAMP'{pdate}', {round(random.uniform(5, 25), 1)}, "
                f"{round(random.uniform(30, 80), 1)}, {round(random.uniform(20, 60), 1)}, "
                f"{round(commitment * 0.3, 1)}, 'Quarterly')"
            )

        if fund_rows:
            _exec_sql(f"INSERT INTO {FUNDS_TABLE} (fund_id, fund_name, manager_name, strategy, vintage_year, aum, commitment, status, domicile, inception_date) VALUES {', '.join(fund_rows)}")
        if perf_rows:
            _exec_sql(f"INSERT INTO {PERFORMANCE_TABLE} (fund_id, date, nav, monthly_return, ytd_return, itd_return, benchmark_return, alpha) VALUES {', '.join(perf_rows)}")
        if hold_rows:
            _exec_sql(f"INSERT INTO {HOLDINGS_TABLE} (fund_id, date, position_name, sector, geography, pct_nav, market_value, change_from_prior) VALUES {', '.join(hold_rows)}")
        if flow_rows:
            _exec_sql(f"INSERT INTO {FLOWS_TABLE} (fund_id, date, capital_calls, distributions, net_flow, commitment_remaining, liquidity_terms) VALUES {', '.join(flow_rows)}")
        total = len(fund_rows) + len(perf_rows) + len(hold_rows) + len(flow_rows)
        return jsonify({"success": True, "injected": total, "funds": len(fund_rows)})
    except Exception as e:
        logger.error(f"Inject good data error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/reset", methods=["POST"])
@require_demo_mode
def reset_demo_data():
    """Delete all injected (GOOD_/ANOM_/BFILL_) data and clear analysis_outputs."""
    try:
        _exec_sql(f"DELETE FROM {PERFORMANCE_TABLE} WHERE fund_id LIKE 'GOOD_%' OR fund_id LIKE 'ANOM_%' OR fund_id LIKE 'BFILL_%'")
        _exec_sql(f"DELETE FROM {HOLDINGS_TABLE} WHERE fund_id LIKE 'GOOD_%' OR fund_id LIKE 'ANOM_%' OR fund_id LIKE 'BFILL_%'")
        _exec_sql(f"DELETE FROM {FLOWS_TABLE} WHERE fund_id LIKE 'GOOD_%' OR fund_id LIKE 'ANOM_%' OR fund_id LIKE 'BFILL_%'")
        _exec_sql(f"DELETE FROM {FUNDS_TABLE} WHERE fund_id LIKE 'GOOD_%' OR fund_id LIKE 'ANOM_%' OR fund_id LIKE 'BFILL_%'")
        try:
            _exec_sql(f"DELETE FROM {ANALYSIS_TABLE} WHERE 1=1")
        except Exception:
            pass
        _shift_data_dates_if_stale()
        return jsonify({"success": True, "message": "Injected data cleared, analyses removed, dates refreshed"})
    except Exception as e:
        logger.error(f"Reset data error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/backfill", methods=["POST"])
@require_demo_mode
def backfill_data():
    """Generate baseline-distribution data for every missing day between last data and today."""
    try:
        import random
        cols, rows = _run_sql(f"SELECT MAX(DATE(date)) FROM {PERFORMANCE_TABLE}")
        if not rows or not rows[0] or rows[0][0] is None:
            return jsonify({"error": "No existing data to backfill from"}), 400
        last_date = datetime.strptime(str(rows[0][0]), "%Y-%m-%d").date()
        today = datetime.utcnow().date()
        gap_days = (today - last_date).days
        if gap_days <= 0:
            return jsonify({"success": True, "days_filled": 0, "funds": 0, "message": "Data is already current"})

        strategies = ["Public Equity", "Private Credit", "Venture Capital", "Real Assets"]
        _, fund_rows = _run_sql(f"SELECT fund_id FROM {FUNDS_TABLE} WHERE fund_id LIKE 'FUND_%' LIMIT 20")
        fund_ids = [r[0] for r in (fund_rows or [])] if fund_rows else ["FUND_BF_1", "FUND_BF_2", "FUND_BF_3"]
        ts = int(datetime.utcnow().timestamp())
        perf_rows, kpi_rows = [], []
        perf_count = 0

        for day_offset in range(1, gap_days + 1):
            target_date = last_date + timedelta(days=day_offset)
            pdate = f"{target_date} 00:00:00"
            for fid in fund_ids[:5]:
                monthly_ret = round(random.uniform(-0.02, 0.04), 4)
                bench_ret = round(random.uniform(-0.01, 0.02), 4)
                alpha_val = round(monthly_ret - bench_ret, 4)
                nav = round(random.uniform(100, 500), 1)
                perf_rows.append(
                    f"('{fid}', TIMESTAMP'{pdate}', {nav}, {monthly_ret}, 0.05, 0.12, {bench_ret}, {alpha_val})"
                )
                perf_count += 1
            for strategy in strategies:
                kpi_rows.append(
                    f"(TIMESTAMP'{pdate}', '{strategy}', {round(random.uniform(500, 3000), 1)}, "
                    f"{round(random.uniform(0, 0.03), 4)}, {round(random.uniform(20, 40), 1)}, "
                    f"{round(random.uniform(0, 0.03), 4)}, {random.randint(3, 10)})"
                )

        if perf_rows:
            for chunk_start in range(0, len(perf_rows), 500):
                chunk = perf_rows[chunk_start:chunk_start + 500]
                _exec_sql(f"INSERT INTO {PERFORMANCE_TABLE} (fund_id, date, nav, monthly_return, ytd_return, itd_return, benchmark_return, alpha) VALUES {', '.join(chunk)}")
        if kpi_rows:
            for chunk_start in range(0, len(kpi_rows), 500):
                chunk = kpi_rows[chunk_start:chunk_start + 500]
                _exec_sql(f"INSERT INTO {KPI_TABLE} (date, portfolio_segment, total_aum, weighted_avg_return, concentration_top5_pct, benchmark_spread, manager_count) VALUES {', '.join(chunk)}")

        logger.info(f"BACKFILL: Filled {gap_days} days with {perf_count} performance rows, {len(kpi_rows)} KPIs")
        return jsonify({"success": True, "days_filled": gap_days, "funds": perf_count})
    except Exception as e:
        logger.error(f"Backfill error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/refresh-dates", methods=["POST"])
def refresh_dates():
    """Shift base data dates forward if stale."""
    try:
        _shift_data_dates_if_stale()
        return jsonify({"success": True, "message": "Date refresh complete"})
    except Exception as e:
        logger.error(f"Refresh dates error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# Legacy heartbeat endpoints
@app.route("/api/heartbeat/status", methods=["GET"])
def heartbeat_status():
    return autonomous_status()

@app.route("/api/heartbeat/start", methods=["POST"])
def heartbeat_start():
    return autonomous_start()

@app.route("/api/heartbeat/stop", methods=["POST"])
def heartbeat_stop():
    return autonomous_stop()


# Health score endpoint
@app.route("/api/health/score", methods=["GET"])
def get_health_score():
    try:
        w = get_workspace_client()
        returns_query = f"""SELECT ROUND(AVG(monthly_return) * 100, 2) as avg_return,
            ROUND(AVG(alpha) * 100, 2) as avg_alpha
            FROM {PERFORMANCE_TABLE} WHERE date > CURRENT_TIMESTAMP - INTERVAL 30 DAYS"""
        conc_query = f"""SELECT ROUND(AVG(concentration_top5_pct), 1) as avg_concentration
            FROM {KPI_TABLE} WHERE date > CURRENT_TIMESTAMP - INTERVAL 7 DAYS"""
        watchlist_query = f"""SELECT COUNT(*) as watchlist_count FROM {FUNDS_TABLE} WHERE status = 'watchlist'"""
        freshness_query = f"""SELECT DATEDIFF(CURRENT_DATE, MAX(DATE(date))) as stale_days FROM {PERFORMANCE_TABLE}"""

        _, ret_rows = _run_sql(returns_query, w)
        _, conc_rows = _run_sql(conc_query, w)
        _, watch_rows = _run_sql(watchlist_query, w)
        _, fresh_rows = _run_sql(freshness_query, w)

        avg_return = float(ret_rows[0][0]) if ret_rows and ret_rows[0][0] is not None else None
        avg_alpha = float(ret_rows[0][1]) if ret_rows and len(ret_rows[0]) > 1 and ret_rows[0][1] is not None else None
        avg_concentration = float(conc_rows[0][0]) if conc_rows and conc_rows[0][0] is not None else 35
        watchlist_count = int(watch_rows[0][0] or 0) if watch_rows else 0
        stale_days = int(fresh_rows[0][0] or 0) if fresh_rows and fresh_rows[0][0] is not None else 30

        _, fund_rows = _run_sql(f"SELECT COUNT(*) FROM {FUNDS_TABLE}", w)
        total_funds = int(fund_rows[0][0] or 0) if fund_rows else 0

        if total_funds == 0:
            return jsonify({"score": None, "avg_return": 0, "avg_alpha": 0, "avg_concentration": 0,
                            "watchlist_count": 0, "total_funds": 0,
                            "summary": "No fund data available. Run seed or use Inject buttons."})

        return_pct = avg_return or 0
        alpha_pct = avg_alpha or 0
        return_score = max(0, min(35, 35 + return_pct * 5))
        alpha_score = max(0, min(40, 40 + alpha_pct * 10))
        conc_score = max(0, min(15, 15 - (avg_concentration - 30) * 0.5))
        freshness_score = max(0, min(10, 10 - stale_days * 0.3))
        health_score = max(0, min(100, int(return_score + alpha_score + conc_score + freshness_score)))

        summary = f"{total_funds} funds tracked, avg return {return_pct:.1f}%, alpha {alpha_pct:.1f}%. "
        if health_score >= 80:
            summary += "Portfolio performing well."
        elif health_score >= 60:
            summary += "Some attention needed."
        else:
            summary += "Critical issues detected."

        _health_score_history.append({"score": health_score, "ts": datetime.utcnow().isoformat()})
        if len(_health_score_history) > 50:
            _health_score_history[:] = _health_score_history[-50:]

        return jsonify({"score": health_score, "avg_return": round(return_pct, 1), "avg_alpha": round(alpha_pct, 1),
                        "avg_concentration": round(avg_concentration, 1), "watchlist_count": watchlist_count,
                        "total_funds": total_funds, "summary": summary})
    except Exception as e:
        logger.error(f"Health score error: {e}", exc_info=True)
        return jsonify({"score": None, "error": str(e)}), 200


@app.route("/api/alerts/active", methods=["GET"])
def get_alerts():
    try:
        w = get_workspace_client()
        query = f"""
        SELECT f.fund_id, f.fund_name, f.strategy, ROUND(AVG(p.monthly_return) * 100, 1) as avg_return,
            ROUND(AVG(p.alpha) * 100, 2) as avg_alpha, COUNT(*) as perf_count
        FROM {FUNDS_TABLE} f
        JOIN {PERFORMANCE_TABLE} p ON f.fund_id = p.fund_id
        WHERE p.date > CURRENT_TIMESTAMP - INTERVAL 30 DAYS
        GROUP BY f.fund_id, f.fund_name, f.strategy
        HAVING AVG(p.monthly_return) < -0.02 OR AVG(p.alpha) < -0.01
        ORDER BY avg_return ASC LIMIT 5
        """
        cols, rows = _run_sql(query, w)
        alerts = []
        if rows:
            for row in rows:
                data = dict(zip(cols, row))
                avg_ret = float(data.get("avg_return", 0) or 0)
                avg_alpha = float(data.get("avg_alpha", 0) or 0)
                alerts.append({
                    "id": f"perf_{data.get('fund_id', '')}",
                    "severity": "high" if avg_ret < -3 else "medium",
                    "title": f"Underperforming: {data.get('fund_name', 'Unknown')}",
                    "detail": f"Avg return {avg_ret}%, alpha {avg_alpha}% over last 30 days"
                })
        return jsonify({"alerts": alerts})
    except Exception as e:
        logger.error(f"Alerts error: {e}", exc_info=True)
        return jsonify({"alerts": [], "error": str(e)}), 200


@app.route("/api/analysis/latest", methods=["GET"])
def get_latest_analysis():
    try:
        w = get_workspace_client()
        limit = min(request.args.get("limit", 10, type=int), 100)
        analysis_type = request.args.get("type")
        if analysis_type and analysis_type not in VALID_ANALYSIS_TYPES:
            return jsonify({"error": "Invalid analysis type"}), 400
        where_clause = f"WHERE analysis_type = '{analysis_type}'" if analysis_type else ""
        query = f"""SELECT id, encounter_id, analysis_type, insights, recommendations, created_at, agent_mode
        FROM {ANALYSIS_TABLE} {where_clause} ORDER BY created_at DESC LIMIT {limit}"""
        cols, rows = _run_sql(query, w)
        analyses = [dict(zip(cols, row)) for row in rows]
        return jsonify({"analyses": analyses, "count": len(analyses)})
    except Exception as e:
        return jsonify({"error": str(e), "analyses": []}), 200


@app.route("/api/recommendations/pending", methods=["GET"])
def get_pending_recommendations():
    try:
        w = get_workspace_client()
        limit = request.args.get("limit", 20, type=int)
        query = f"""SELECT id, encounter_id, analysis_type, insights, recommendations, created_at, priority, status
        FROM {ANALYSIS_TABLE} WHERE status = 'pending' AND recommendations IS NOT NULL
        ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END,
        created_at DESC LIMIT {limit}"""
        cols, rows = _run_sql(query, w)
        recommendations = [dict(zip(cols, row)) for row in rows]
        return jsonify({"recommendations": recommendations})
    except Exception as e:
        return jsonify({"error": str(e), "recommendations": []}), 200


@app.route("/api/recommendations/<rec_id>/approve", methods=["POST"])
def approve_recommendation(rec_id):
    if not UUID_RE.match(rec_id):
        return jsonify({"error": "Invalid recommendation ID"}), 400
    try:
        data = request.json or {}
        reviewed_by = data.get("reviewed_by", "unknown").replace("'", "''")
        engineer_notes = data.get("engineer_notes", "").replace("'", "''")
        query = f"""UPDATE {ANALYSIS_TABLE} SET status = 'approved', reviewed_by = '{reviewed_by}',
        reviewed_at = current_timestamp(), engineer_notes = '{engineer_notes}' WHERE id = '{rec_id}'"""
        _exec_sql(query)
        return jsonify({"success": True, "id": rec_id, "status": "approved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/recommendations/<rec_id>/reject", methods=["POST"])
def reject_recommendation(rec_id):
    if not UUID_RE.match(rec_id):
        return jsonify({"error": "Invalid recommendation ID"}), 400
    try:
        data = request.json or {}
        reviewed_by = data.get("reviewed_by", "unknown").replace("'", "''")
        engineer_notes = data.get("engineer_notes", "").replace("'", "''")
        query = f"""UPDATE {ANALYSIS_TABLE} SET status = 'rejected', reviewed_by = '{reviewed_by}',
        reviewed_at = current_timestamp(), engineer_notes = '{engineer_notes}' WHERE id = '{rec_id}'"""
        _exec_sql(query)
        return jsonify({"success": True, "id": rec_id, "status": "rejected"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/recommendations/<rec_id>/export-pdf", methods=["POST"])
def export_recommendation_pdf(rec_id):
    try:
        w = get_workspace_client()
        query = f"""SELECT id, encounter_id, analysis_type, insights, recommendations, created_at, priority, status
        FROM {ANALYSIS_TABLE} WHERE id = '{rec_id}'"""
        cols, rows = _run_sql(query, w)
        if rows:
            rec = dict(zip(cols, rows[0]))
            report = f"""
INVESTMENT ACTION REPORT
{'='*60}

Recommendation ID: {rec['id']}
Fund ID: {rec.get('encounter_id', 'N/A')}
Analysis Type: {rec['analysis_type']}
Priority: {rec.get('priority', 'Not Set').upper()}
Created: {rec['created_at']}
Status: {rec['status']}

FINDINGS
{'-'*60}
{rec['insights']}

RECOMMENDATIONS
{'-'*60}
{rec.get('recommendations', 'No recommendations provided')}

SIGN-OFF
{'-'*60}
Portfolio Manager Signature: ______________________  Date: __________
Notes:


{'='*60}
End of Report
"""
            return jsonify({"success": True, "report": report, "filename": f"recommendation_{rec_id}.txt"})
        return jsonify({"error": "Recommendation not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ed/summary", methods=["GET"])
def get_ed_summary():
    """Fund flows: capital calls vs distributions by liquidity terms."""
    try:
        w = get_workspace_client()
        query = f"""SELECT liquidity_terms,
            ROUND(SUM(capital_calls), 1) as total_calls,
            ROUND(SUM(distributions), 1) as total_dist,
            ROUND(SUM(net_flow), 1) as net_flow,
            COUNT(*) as flow_count
        FROM {FLOWS_TABLE}
        WHERE date >= CURRENT_TIMESTAMP - INTERVAL 30 DAYS
        GROUP BY liquidity_terms ORDER BY total_calls DESC"""
        cols, rows = _run_sql(query, w)
        levels = []
        total_breaches = 0
        for row in rows:
            d = dict(zip(cols, row))
            levels.append({
                "acuity": d.get("liquidity_terms", "Unknown"),
                "avg_wait": float(d.get("total_calls") or 0),
                "total": int(d.get("flow_count") or 0),
                "breaches": int(d.get("total_dist") or 0),
            })
        return jsonify({"levels": levels, "total_breaches": total_breaches})
    except Exception as e:
        return jsonify({"error": str(e), "levels": [], "total_breaches": 0}), 200


@app.route("/api/drugs/summary", methods=["GET"])
def get_drugs_summary():
    """AUM trend by strategy segment."""
    try:
        w = get_workspace_client()
        total_q = f"SELECT ROUND(SUM(total_aum), 2) as total_spend FROM {KPI_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS"
        cat_q = f"""SELECT portfolio_segment, ROUND(SUM(total_aum), 2) as spend
            FROM {KPI_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS
            GROUP BY portfolio_segment ORDER BY spend DESC LIMIT 5"""
        _, total_rows = _run_sql(total_q, w)
        cat_cols, cat_rows = _run_sql(cat_q, w)
        total_spend = float(total_rows[0][0] or 0) if total_rows else 0
        categories = []
        for row in cat_rows:
            d = dict(zip(cat_cols, row))
            categories.append({"category": d.get("portfolio_segment"), "spend": float(d.get("spend") or 0)})
        return jsonify({"total_spend": total_spend, "categories": categories})
    except Exception as e:
        return jsonify({"error": str(e), "total_spend": 0, "categories": []}), 200


@app.route("/api/staffing/summary", methods=["GET"])
def get_staffing_summary():
    """Sector and geography exposure from holdings."""
    try:
        w = get_workspace_client()
        query = f"""SELECT sector,
            ROUND(SUM(pct_nav), 1) as total_pct,
            COUNT(*) as position_count
        FROM {HOLDINGS_TABLE}
        WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS
        GROUP BY sector ORDER BY total_pct DESC"""
        cols, rows = _run_sql(query, w)
        departments = []
        overall_contract = 0
        overall_total = 0
        for row in rows:
            d = dict(zip(cols, row))
            pct = float(d.get("total_pct") or 0)
            cnt = int(d.get("position_count") or 0)
            overall_contract += pct
            overall_total += cnt
            departments.append({"department": d.get("sector"), "contract_pct": pct, "total_fte": cnt})
        overall_pct = round(overall_contract / len(departments), 1) if departments else 0
        return jsonify({"overall_contract_pct": overall_pct, "departments": departments[:5]})
    except Exception as e:
        return jsonify({"error": str(e), "overall_contract_pct": 0, "departments": []}), 200


@app.route("/api/encounters/summary", methods=["GET"])
def get_encounter_summary():
    """Portfolio summary: fund count, watchlist, returns."""
    try:
        w = get_workspace_client()
        query = f"""SELECT COUNT(*) as total_encounters,
               SUM(CASE WHEN status = 'watchlist' THEN 1 ELSE 0 END) as readmissions,
               COUNT(DISTINCT strategy) as hospital_count,
               ROUND(SUM(aum), 1) as avg_los
        FROM {FUNDS_TABLE}"""
        trend_query = f"""SELECT
            ROUND(AVG(CASE WHEN p.date > CURRENT_TIMESTAMP - INTERVAL 7 DAYS THEN p.monthly_return END) * 100, 2) as this_week_los,
            ROUND(AVG(CASE WHEN p.date BETWEEN CURRENT_TIMESTAMP - INTERVAL 14 DAYS AND CURRENT_TIMESTAMP - INTERVAL 7 DAYS THEN p.monthly_return END) * 100, 2) as last_week_los,
            SUM(CASE WHEN p.date > CURRENT_TIMESTAMP - INTERVAL 7 DAYS AND f.status = 'watchlist' THEN 1 ELSE 0 END) as this_week_readmits,
            SUM(CASE WHEN p.date BETWEEN CURRENT_TIMESTAMP - INTERVAL 14 DAYS AND CURRENT_TIMESTAMP - INTERVAL 7 DAYS AND f.status = 'watchlist' THEN 1 ELSE 0 END) as last_week_readmits,
            SUM(CASE WHEN p.date > CURRENT_TIMESTAMP - INTERVAL 7 DAYS THEN 1 ELSE 0 END) as this_week_enc,
            SUM(CASE WHEN p.date BETWEEN CURRENT_TIMESTAMP - INTERVAL 14 DAYS AND CURRENT_TIMESTAMP - INTERVAL 7 DAYS THEN 1 ELSE 0 END) as last_week_enc
        FROM {PERFORMANCE_TABLE} p
        JOIN {FUNDS_TABLE} f ON p.fund_id = f.fund_id
        WHERE p.date > CURRENT_TIMESTAMP - INTERVAL 14 DAYS"""
        cols, rows = _run_sql(query, w)
        summary = {}
        if rows:
            summary = dict(zip(cols, rows[0]))
            total = int(summary.get("total_encounters", 0) or 0)
            readmits = int(summary.get("readmissions", 0) or 0)
            summary["readmission_rate"] = round(readmits / total * 100, 1) if total > 0 else 0
        trends = {}
        try:
            tcols, trows = _run_sql(trend_query, w)
            if trows:
                td = dict(zip(tcols, trows[0]))
                tw_los = float(td.get("this_week_los") or 0)
                lw_los = float(td.get("last_week_los") or 0)
                tw_re = int(td.get("this_week_readmits") or 0)
                lw_re = int(td.get("last_week_readmits") or 0)
                tw_enc = int(td.get("this_week_enc") or 0)
                lw_enc = int(td.get("last_week_enc") or 0)
                if lw_los and abs(lw_los) > 0.001:
                    trends["los_trend"] = round((tw_los - lw_los) / abs(lw_los) * 100, 1)
                if lw_re > 0:
                    trends["readmit_trend"] = round((tw_re - lw_re) / lw_re * 100, 1)
                if lw_enc > 0:
                    trends["enc_trend"] = round((tw_enc - lw_enc) / lw_enc * 100, 1)
        except Exception:
            pass
        summary["trends"] = trends
        return jsonify({"summary": summary})
    except Exception as e:
        return jsonify({"error": str(e), "summary": {}}), 200


@app.route("/api/encounters/by-hospital", methods=["GET"])
def get_encounters_by_hospital():
    """Fund stats by manager."""
    try:
        w = get_workspace_client()
        query = f"""SELECT manager_name as hospital, COUNT(*) as encounter_count,
               SUM(CASE WHEN status = 'watchlist' THEN 1 ELSE 0 END) as readmission_count,
               ROUND(SUM(aum), 1) as avg_los
        FROM {FUNDS_TABLE} GROUP BY manager_name ORDER BY avg_los DESC"""
        cols, rows = _run_sql(query, w)
        data = [dict(zip(cols, row)) for row in rows]
        return jsonify({"hospital_stats": data})
    except Exception as e:
        return jsonify({"error": str(e), "hospital_stats": []}), 200


@app.route("/api/encounters/by-department", methods=["GET"])
def get_encounters_by_department():
    """Fund stats by strategy."""
    try:
        w = get_workspace_client()
        query = f"""SELECT strategy as department, COUNT(*) as encounter_count,
               SUM(CASE WHEN status = 'watchlist' THEN 1 ELSE 0 END) as readmission_count,
               ROUND(SUM(aum), 1) as avg_los
        FROM {FUNDS_TABLE} GROUP BY strategy ORDER BY encounter_count DESC"""
        cols, rows = _run_sql(query, w)
        data = [dict(zip(cols, row)) for row in rows]
        return jsonify({"department_stats": data})
    except Exception as e:
        return jsonify({"error": str(e), "department_stats": []}), 200


@app.route("/api/encounters/timeline", methods=["GET"])
def get_encounters_timeline():
    """Fund performance timeline: monthly returns by strategy."""
    try:
        w = get_workspace_client()
        days = request.args.get("days", 30, type=int)
        query = f"""SELECT DATE(p.date) as encounter_date,
               COUNT(DISTINCT p.fund_id) as encounter_count,
               ROUND(AVG(p.monthly_return) * 100, 2) as readmission_count
        FROM {PERFORMANCE_TABLE} p
        JOIN {FUNDS_TABLE} f ON p.fund_id = f.fund_id
        WHERE p.date >= CURRENT_DATE - INTERVAL {days} DAYS
        GROUP BY DATE(p.date) ORDER BY encounter_date ASC"""
        cols, rows = _run_sql(query, w)
        timeline = []
        for row in rows:
            data = dict(zip(cols, row))
            timeline.append({"date": str(data.get("encounter_date")),
                             "encounters": int(data.get("encounter_count", 0) or 0),
                             "readmissions": float(data.get("readmission_count", 0) or 0)})
        return jsonify({"timeline": timeline, "days": days})
    except Exception as e:
        return jsonify({"error": str(e), "timeline": []}), 200


@app.route("/api/encounters/readmissions", methods=["GET"])
def get_readmissions():
    """Watchlist / underperforming funds table."""
    try:
        w = get_workspace_client()
        limit = request.args.get("limit", 5, type=int)
        query = f"""SELECT f.fund_id as encounter_id, f.manager_name as hospital, f.strategy as department,
            ROUND(COALESCE(AVG(p.monthly_return) * 100, 0), 1) as los_days,
            MAX(p.date) as admit_date,
            MAX(p.date) as discharge_date,
            f.status as payer,
            ROUND(COALESCE(AVG(p.alpha) * 100, 0), 2) as total_drug_cost
        FROM {FUNDS_TABLE} f
        LEFT JOIN {PERFORMANCE_TABLE} p ON f.fund_id = p.fund_id AND p.date >= CURRENT_DATE - INTERVAL 90 DAYS
        WHERE f.status = 'watchlist'
        GROUP BY f.fund_id, f.manager_name, f.strategy, f.status
        ORDER BY total_drug_cost ASC LIMIT {limit}"""
        cols, rows = _run_sql(query, w)
        readmissions = []
        for row in rows:
            data = dict(zip(cols, row))
            readmissions.append({
                "encounter_id": data.get("encounter_id"), "hospital": data.get("hospital"),
                "department": data.get("department"), "los_days": data.get("los_days"),
                "admit_date": str(data.get("admit_date")),
                "discharge_date": str(data.get("discharge_date", "")),
                "payer": data.get("payer"),
                "total_drug_cost": float(data.get("total_drug_cost") or 0),
            })
        return jsonify({"readmissions": readmissions, "count": len(readmissions)})
    except Exception as e:
        return jsonify({"error": str(e), "readmissions": []}), 200


import re as _re

def _format_recommendation(text):
    """Convert old-style prose recommendations into markdown for display."""
    if not text or '\n' in text:
        return text
    t = _re.sub(r'(HIGH PRIORITY|MEDIUM PRIORITY|LOW PRIORITY|CRITICAL)\s*:', r'\n\n**\1:**\n\n', text)
    t = _re.sub(r';\s*\((\d+)\)\s*', r'\n\n\1. ', t)
    t = _re.sub(r'\((\d+)\)\s*', r'\n\n\1. ', t)
    return t.strip()


@app.route("/api/recommendations/latest", methods=["GET"])
def get_recommendations():
    try:
        w = get_workspace_client()
        limit = request.args.get("limit", 5, type=int)
        query = f"""SELECT id, encounter_id, analysis_type, insights, recommendations, created_at
        FROM {ANALYSIS_TABLE} WHERE recommendations IS NOT NULL AND recommendations != ''
        ORDER BY created_at DESC LIMIT {limit}"""
        cols, rows = _run_sql(query, w)
        recommendations = []
        for row in rows:
            data = dict(zip(cols, row))
            recommendations.append({
                "id": data.get("id"), "encounter_id": data.get("encounter_id"),
                "type": data.get("analysis_type"),
                "insight": (data.get("insights", "")[:200] + "...") if len(data.get("insights", "")) > 200 else data.get("insights", ""),
                "action": _format_recommendation(data.get("recommendations", "")),
                "created_at": data.get("created_at"),
                "timestamp": data.get("created_at"),
            })
        return jsonify({"recommendations": recommendations, "count": len(recommendations)})
    except Exception as e:
        return jsonify({"error": str(e), "recommendations": []}), 200


@app.route("/api/encounters/los-by-dept", methods=["GET"])
def get_los_by_dept():
    """Returns by strategy."""
    try:
        w = get_workspace_client()
        query = f"""SELECT f.strategy as department,
            ROUND(AVG(p.monthly_return) * 100, 1) as avg_los,
            COUNT(*) as enc_count
            FROM {PERFORMANCE_TABLE} p
            JOIN {FUNDS_TABLE} f ON p.fund_id = f.fund_id
            WHERE p.date >= CURRENT_DATE - INTERVAL 30 DAYS
            GROUP BY f.strategy ORDER BY avg_los DESC"""
        cols, rows = _run_sql(query, w)
        depts = [dict(zip(cols, row)) for row in rows]
        for d in depts:
            d["avg_los"] = float(d.get("avg_los") or 0)
            d["enc_count"] = int(d.get("enc_count") or 0)
        return jsonify({"departments": depts})
    except Exception as e:
        return jsonify({"error": str(e), "departments": []}), 200


@app.route("/api/encounters/payer-mix", methods=["GET"])
def get_payer_mix():
    """Strategy allocation pie."""
    try:
        w = get_workspace_client()
        query = f"""SELECT strategy as payer, COUNT(*) as enc_count
            FROM {FUNDS_TABLE} GROUP BY strategy ORDER BY enc_count DESC LIMIT 6"""
        cols, rows = _run_sql(query, w)
        payers = [{"payer": r[0], "count": int(r[1] or 0)} for r in rows]
        return jsonify({"payers": payers})
    except Exception as e:
        return jsonify({"error": str(e), "payers": []}), 200


@app.route("/api/health/history", methods=["GET"])
def get_health_history():
    return jsonify({"history": _health_score_history[-20:]})


@app.route("/api/suggestions", methods=["GET"])
def get_suggestions():
    """Return context-aware suggested questions based on current portfolio data."""
    suggestions = []
    try:
        w = get_workspace_client()
        _, ret_rows = _run_sql(f"SELECT ROUND(AVG(monthly_return)*100,1) FROM {PERFORMANCE_TABLE} WHERE date > CURRENT_TIMESTAMP - INTERVAL 30 DAYS", w)
        avg_return = float(ret_rows[0][0] or 0) if ret_rows and ret_rows[0][0] is not None else 0
        _, watch_rows = _run_sql(f"SELECT ROUND(SUM(CASE WHEN status='watchlist' THEN 1 ELSE 0 END)*100.0/NULLIF(COUNT(*),0),1) FROM {FUNDS_TABLE}", w)
        watchlist_pct = float(watch_rows[0][0] or 0) if watch_rows and watch_rows[0][0] is not None else 0
        _, conc_rows = _run_sql(f"SELECT ROUND(AVG(concentration_top5_pct),1) FROM {KPI_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 7 DAYS", w)
        avg_conc = float(conc_rows[0][0] or 0) if conc_rows and conc_rows[0][0] is not None else 0
        _, alpha_rows = _run_sql(f"SELECT ROUND(AVG(alpha)*100,1) FROM {PERFORMANCE_TABLE} WHERE date > CURRENT_TIMESTAMP - INTERVAL 30 DAYS", w)
        avg_alpha = float(alpha_rows[0][0] or 0) if alpha_rows and alpha_rows[0][0] is not None else 0

        if watchlist_pct > 15:
            suggestions.append({"label": f"Watchlist: {watchlist_pct}% of funds on watchlist",
                                "query": f"{watchlist_pct}% of funds are on the watchlist. Analyze which strategies and managers are underperforming and recommend rebalancing or exit actions."})
        if avg_return < 1:
            suggestions.append({"label": f"Performance: Portfolio return {avg_return}% this month",
                                "query": f"Portfolio monthly return is {avg_return}%. Which funds and strategies are dragging performance? Compare to benchmark and recommend actions."})
        if avg_conc > 45:
            suggestions.append({"label": f"Concentration: Top 5 concentration at {avg_conc}%",
                                "query": f"Portfolio concentration (top 5 funds) is {avg_conc}%, above target. Which strategies are over-concentrated? Recommend diversification steps."})
        if avg_alpha < 0:
            suggestions.append({"label": f"Alpha: Negative alpha of {avg_alpha}%",
                                "query": f"Portfolio alpha is {avg_alpha}% vs benchmark. Which funds are underperforming? Search our investment policy for concentration and rebalancing guidelines."})

        fallbacks = [
            {"label": "What are the top performing funds this quarter?",
             "query": "Based on all current performance data, which funds have the highest returns and positive alpha this quarter? Break down by strategy."},
            {"label": "Show me portfolio concentration by strategy",
             "query": "Analyze portfolio concentration by strategy. Which strategies have the highest top-5 fund concentration? Are we within policy limits?"},
            {"label": "Compare fund flows: capital calls vs distributions",
             "query": "Compare capital calls and distributions across funds. Which strategies have the highest net capital calls? Are there liquidity concerns?"},
            {"label": "What does our investment policy say about concentration?",
             "query": "Search our investment policy documents for guidance on concentration limits and rebalancing. Summarize the key constraints."},
            {"label": "Create a portfolio rebalancing plan",
             "query": "Analyze current allocation vs target. Where are we over or under weight by strategy? Create a quarterly rebalancing plan with specific fund actions."},
        ]
        for fb in fallbacks:
            if len(suggestions) >= 5:
                break
            suggestions.append(fb)
    except Exception as e:
        logger.warning(f"Suggestions error: {e}")
        suggestions = [
            {"label": "What are the top performing funds this quarter?",
             "query": "Which funds have the highest returns and positive alpha this quarter?"},
            {"label": "Show me portfolio concentration by strategy",
             "query": "Analyze portfolio concentration by strategy. Which strategies have the highest concentration?"},
            {"label": "What does our investment policy say about concentration?",
             "query": "Search our investment policy for guidance on concentration limits and rebalancing."},
        ]
    return jsonify({"suggestions": suggestions[:5]})


@app.route("/api/autonomous/latest-result", methods=["GET"])
def autonomous_latest_result():
    return jsonify(_autonomous_latest_result)


def record_autonomous_result(message, issues_found):
    """Called by the autonomous agent after a health check completes."""
    global _autonomous_latest_result
    _autonomous_latest_result = {
        "timestamp": datetime.utcnow().isoformat(),
        "message": message,
        "issues_found": issues_found,
    }



# ---------------------------------------------------------------------------
# New /api/dashboard/* endpoints matching the React frontend
# ---------------------------------------------------------------------------

@app.route("/api/dashboard/summary", methods=["GET"])
def dashboard_summary():
    """Portfolio summary for stat cards."""
    try:
        w = get_workspace_client()
        _, f_rows = _run_sql(f"SELECT COUNT(*) as cnt, ROUND(SUM(aum),1) as total_aum, SUM(CASE WHEN status='watchlist' THEN 1 ELSE 0 END) as wl FROM {FUNDS_TABLE}", w)
        fund_data = dict(zip(["cnt", "total_aum", "wl"], f_rows[0])) if f_rows else {}
        _, r_rows = _run_sql(f"SELECT ROUND(AVG(monthly_return)*100,2) as avg_ret, ROUND(AVG(alpha)*100,2) as avg_alpha FROM {PERFORMANCE_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS", w)
        ret_data = dict(zip(["avg_ret", "avg_alpha"], r_rows[0])) if r_rows else {}
        _, c_rows = _run_sql(f"SELECT ROUND(AVG(concentration_top5_pct),1) as conc FROM {KPI_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 7 DAYS", w)
        conc = float(c_rows[0][0] or 0) if c_rows and c_rows[0][0] else 0
        total_aum = float(fund_data.get("total_aum") or 0)
        avg_return = float(ret_data.get("avg_ret") or 0)
        watchlist_count = int(fund_data.get("wl") or 0)
        return jsonify({
            "total_aum": total_aum, "avg_return": avg_return,
            "concentration_pct": conc, "watchlist_count": watchlist_count,
            "trends": {}
        })
    except Exception as e:
        return jsonify({"total_aum": 0, "avg_return": 0, "concentration_pct": 0, "watchlist_count": 0, "trends": {}, "error": str(e)}), 200


@app.route("/api/dashboard/fund-performance", methods=["GET"])
def dashboard_fund_performance():
    """Monthly returns by strategy for line chart."""
    try:
        w = get_workspace_client()
        months = request.args.get("months", 12, type=int)
        query = f"""
        SELECT DATE_FORMAT(p.date, 'yyyy-MM') as period, f.strategy,
               ROUND(AVG(p.monthly_return)*100, 2) as avg_ret
        FROM {PERFORMANCE_TABLE} p JOIN {FUNDS_TABLE} f ON p.fund_id = f.fund_id
        WHERE p.date >= ADD_MONTHS(CURRENT_DATE, -{months})
        GROUP BY DATE_FORMAT(p.date, 'yyyy-MM'), f.strategy
        ORDER BY period"""
        cols, rows = _run_sql(query, w)
        pivot = {}
        strategies = set()
        for row in rows:
            d = dict(zip(cols, row))
            period = d["period"]
            strat = d["strategy"]
            strategies.add(strat)
            if period not in pivot:
                pivot[period] = {"period": period}
            pivot[period][strat] = float(d["avg_ret"] or 0)
        series = sorted(pivot.values(), key=lambda x: x["period"])
        return jsonify({"series": series, "xKey": "period", "yKeys": sorted(strategies), "strategies": sorted(strategies)})
    except Exception as e:
        return jsonify({"series": [], "strategies": [], "error": str(e)}), 200


@app.route("/api/dashboard/watchlist", methods=["GET"])
def dashboard_watchlist():
    """Watchlist/underperforming funds table."""
    try:
        w = get_workspace_client()
        limit = request.args.get("limit", 5, type=int)
        query = f"""SELECT f.fund_name, f.manager_name, f.strategy, f.aum,
            ROUND(COALESCE(AVG(p.monthly_return)*100,0),2) as return_pct,
            MAX(p.date) as flagged_date
        FROM {FUNDS_TABLE} f
        LEFT JOIN {PERFORMANCE_TABLE} p ON f.fund_id = p.fund_id AND p.date >= CURRENT_DATE - INTERVAL 90 DAYS
        WHERE f.status = 'watchlist'
        GROUP BY f.fund_name, f.manager_name, f.strategy, f.aum
        ORDER BY return_pct ASC LIMIT {limit}"""
        cols, rows = _run_sql(query, w)
        funds = []
        for row in rows:
            d = dict(zip(cols, row))
            funds.append({
                "fund_name": d.get("fund_name"), "manager": d.get("manager_name"),
                "strategy": d.get("strategy"), "aum": float(d.get("aum") or 0),
                "return_pct": float(d.get("return_pct") or 0),
                "flagged_date": str(d.get("flagged_date", "")),
            })
        return jsonify({"funds": funds, "watchlist": funds})
    except Exception as e:
        return jsonify({"funds": [], "watchlist": [], "error": str(e)}), 200


@app.route("/api/dashboard/capital-flows", methods=["GET"])
def dashboard_capital_flows():
    """Capital calls vs distributions by strategy."""
    try:
        w = get_workspace_client()
        query = f"""SELECT f.strategy,
            ROUND(SUM(fl.capital_calls),1) as capital_calls,
            ROUND(SUM(fl.distributions),1) as distributions
        FROM {FLOWS_TABLE} fl JOIN {FUNDS_TABLE} f ON fl.fund_id = f.fund_id
        WHERE fl.date >= CURRENT_DATE - INTERVAL 90 DAYS
        GROUP BY f.strategy ORDER BY capital_calls DESC"""
        cols, rows = _run_sql(query, w)
        strategies = [dict(zip(cols, row)) for row in rows]
        for s in strategies:
            s["capital_calls"] = float(s.get("capital_calls") or 0)
            s["distributions"] = float(s.get("distributions") or 0)
        return jsonify({"strategies": strategies})
    except Exception as e:
        return jsonify({"strategies": [], "error": str(e)}), 200


@app.route("/api/dashboard/aum-trend", methods=["GET"])
def dashboard_aum_trend():
    """AUM over time."""
    try:
        w = get_workspace_client()
        query = f"""SELECT DATE_FORMAT(date, 'yyyy-MM') as period,
            ROUND(AVG(total_aum),1) as aum
        FROM {KPI_TABLE}
        WHERE date >= ADD_MONTHS(CURRENT_DATE, -12)
        GROUP BY DATE_FORMAT(date, 'yyyy-MM') ORDER BY period"""
        cols, rows = _run_sql(query, w)
        series = [{"period": r[0], "aum": float(r[1] or 0)} for r in rows]
        return jsonify({"series": series})
    except Exception as e:
        return jsonify({"series": [], "error": str(e)}), 200


@app.route("/api/dashboard/sector-exposure", methods=["GET"])
def dashboard_sector_exposure():
    """Sector allocation from holdings."""
    try:
        w = get_workspace_client()
        query = f"""SELECT sector, ROUND(AVG(pct_nav),2) as pct
        FROM {HOLDINGS_TABLE}
        WHERE date >= CURRENT_DATE - INTERVAL 90 DAYS
        GROUP BY sector ORDER BY pct DESC LIMIT 8"""
        cols, rows = _run_sql(query, w)
        sectors = [{"sector": r[0], "pct": float(r[1] or 0)} for r in rows]
        return jsonify({"sectors": sectors})
    except Exception as e:
        return jsonify({"sectors": [], "error": str(e)}), 200


@app.route("/api/dashboard/returns-by-strategy", methods=["GET"])
def dashboard_returns_by_strategy():
    """Average monthly return by strategy."""
    try:
        w = get_workspace_client()
        query = f"""SELECT f.strategy, ROUND(AVG(p.monthly_return)*100,2) as avg_return
        FROM {PERFORMANCE_TABLE} p JOIN {FUNDS_TABLE} f ON p.fund_id = f.fund_id
        WHERE p.date >= CURRENT_DATE - INTERVAL 90 DAYS
        GROUP BY f.strategy ORDER BY avg_return DESC"""
        cols, rows = _run_sql(query, w)
        strategies = [{"strategy": r[0], "avg_return": float(r[1] or 0)} for r in rows]
        return jsonify({"strategies": strategies})
    except Exception as e:
        return jsonify({"strategies": [], "error": str(e)}), 200


@app.route("/api/dashboard/strategy-allocation", methods=["GET"])
def dashboard_strategy_allocation():
    """Fund count by strategy for pie chart."""
    try:
        w = get_workspace_client()
        query = f"""SELECT strategy, COUNT(*) as cnt,
            ROUND(COUNT(*)*100.0 / (SELECT COUNT(*) FROM {FUNDS_TABLE}), 1) as pct
        FROM {FUNDS_TABLE} GROUP BY strategy ORDER BY cnt DESC"""
        cols, rows = _run_sql(query, w)
        strategies = [{"strategy": r[0], "count": int(r[1] or 0), "pct": float(r[2] or 0)} for r in rows]
        return jsonify({"strategies": strategies})
    except Exception as e:
        return jsonify({"strategies": [], "error": str(e)}), 200


@app.route("/api/dashboard/health-history", methods=["GET"])
def dashboard_health_history():
    """Health score history."""
    return jsonify({"history": _health_score_history[-20:]})


DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
VISIBLE_DOCS = {"WALKTHROUGH", "AGENT_ARCHITECTURE"}


@app.route("/api/docs", methods=["GET"])
def list_docs():
    """List available documentation files."""
    docs = []
    if os.path.isdir(DOCS_DIR):
        for f in sorted(os.listdir(DOCS_DIR)):
            if f.endswith(".md"):
                name = f[:-3]
                if name not in VISIBLE_DOCS:
                    continue
                title = name.replace("_", " ").title()
                docs.append({"name": name, "filename": f, "title": title})
    return jsonify({"docs": docs})


@app.route("/api/docs/<name>", methods=["GET"])
def get_doc(name):
    """Return markdown content of a doc file."""
    safe_name = os.path.basename(name)
    path = os.path.join(DOCS_DIR, f"{safe_name}.md")
    if not os.path.isfile(path):
        return jsonify({"error": "Doc not found"}), 404
    with open(path, "r") as fh:
        content = fh.read()
    title = content.split("\n")[0].lstrip("# ").strip() if content.startswith("#") else safe_name
    return jsonify({"name": safe_name, "title": title, "content": content})


if __name__ == "__main__":
    load_agent()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
