"""Flask server for Hospital Control Tower App."""
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
    "cost_monitoring", "los_analysis", "ed_performance", "staffing_analysis",
    "next_best_action_report", "compliance_monitoring", "strategy_optimization", "learning_reflection",
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
    ANALYSIS_TABLE, ENCOUNTERS_TABLE, DRUG_COSTS_TABLE,
    ED_WAIT_TABLE, STAFFING_TABLE,
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
logger.info(f"  ENCOUNTERS    = {ENCOUNTERS_TABLE!r}")
logger.info(f"  DRUG_COSTS    = {DRUG_COSTS_TABLE!r}")
logger.info(f"  STAFFING      = {STAFFING_TABLE!r}")
logger.info(f"  ED_WAIT       = {ED_WAIT_TABLE!r}")
logger.info(f"  ANALYSIS      = {ANALYSIS_TABLE!r}")
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
            encounter_id STRING COMMENT 'Related encounter ID',
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
    """If the most recent encounter is older than 7 days, shift ALL table dates forward so data stays fresh."""
    if not WAREHOUSE_ID or not CATALOG:
        return
    try:
        cols, rows = _run_sql(f"SELECT DATEDIFF(CURRENT_DATE, MAX(DATE(admit_date))) as stale_days FROM {ENCOUNTERS_TABLE}")
        if not rows or not rows[0] or rows[0][0] is None:
            logger.info("SEED: No encounter data found, skipping date shift")
            return
        stale_days = int(rows[0][0])
        if stale_days <= 3:
            logger.info(f"SEED: Data is fresh (most recent encounter {stale_days} days ago)")
            return
        shift = stale_days - 1
        logger.info(f"SEED: Data is {stale_days} days stale -- shifting all dates forward by {shift} days")
        _exec_sql(f"UPDATE {ENCOUNTERS_TABLE} SET admit_date = DATE_ADD(admit_date, {shift}), discharge_date = DATE_ADD(discharge_date, {shift})")
        _exec_sql(f"UPDATE {ED_WAIT_TABLE} SET arrival_time = arrival_time + INTERVAL {shift} DAYS")
        _exec_sql(f"UPDATE {DRUG_COSTS_TABLE} SET date = DATE_ADD(date, {shift})")
        _exec_sql(f"UPDATE {STAFFING_TABLE} SET date = DATE_ADD(date, {shift})")
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
            f"SELECT COUNT(*) FROM {ENCOUNTERS_TABLE} WHERE admit_date >= CURRENT_DATE - INTERVAL 30 DAYS"
        )
        count = int(rows[0][0] or 0) if rows else 0

        if count >= 20:
            logger.info(f"SEED: {count} recent encounters found, skipping seed")
            return

        logger.info("SEED: No recent encounters -- seeding baseline demo data")
        now = datetime.utcnow()
        hospitals = ["Hospital_A", "Hospital_B", "Hospital_C"]
        depts = ["Cardiology", "Orthopedics", "General_Medicine", "Neurology", "Pediatrics", "Emergency"]
        payers = ["BlueCross", "Medicare", "Aetna", "UnitedHealth", "Cigna"]
        drug_cats = ["Antibiotics", "Analgesics", "Cardiovascular", "Oncology", "Respiratory"]
        drug_names = ["Amoxicillin", "Ibuprofen", "Lisinopril", "Metformin", "Atorvastatin",
                      "Omeprazole", "Amlodipine", "Albuterol", "Gabapentin", "Losartan"]
        staff_types = ["full_time", "contract"]

        enc_rows, ed_rows, drug_rows, staff_rows = [], [], [], []

        for i in range(50):
            days_ago = random.randint(0, 29)
            los = round(random.uniform(1.5, 8.0), 1)
            is_readmit = random.random() < 0.08
            hosp = random.choice(hospitals)
            dept = random.choice(depts)
            admit = (now - timedelta(days=days_ago + los)).strftime("%Y-%m-%d")
            discharge = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            eid = f"SEED_{int(now.timestamp())}_{i:03d}"

            enc_rows.append(
                f"('{eid}', 'PAT_SEED_{i}', '{hosp}', '{dept}', '{random.choice(payers)}', "
                f"'{admit}', '{discharge}', {los}, {str(is_readmit).lower()}, 'Dr. Baseline')"
            )

            if random.random() < 0.6:
                acuity = random.randint(1, 5)
                wait = round(random.uniform(5, 90 if acuity > 2 else 30), 1)
                arrival = (now - timedelta(days=days_ago, hours=random.randint(0, 23))).strftime("%Y-%m-%d %H:%M:%S")
                ed_rows.append(f"('{eid}', '{hosp}', {acuity}, {wait}, TIMESTAMP'{arrival}')")

            for _ in range(random.randint(1, 3)):
                drug = random.choice(drug_names)
                cat = random.choice(drug_cats)
                qty = random.randint(1, 30)
                unit_cost = round(random.uniform(5, 200), 2)
                total = round(qty * unit_cost, 2)
                odate = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                drug_rows.append(f"('{eid}', '{drug}', '{cat}', {qty}, {unit_cost}, {total}, '{odate}')")

        for week in range(4):
            rdate = (now - timedelta(weeks=week)).strftime("%Y-%m-%d")
            for dept in depts:
                for st in staff_types:
                    fte = round(random.uniform(5, 30), 1)
                    staff_rows.append(f"('{random.choice(hospitals)}', '{dept}', '{st}', {fte}, '{rdate}')")

        stmts = []
        if enc_rows:
            stmts.append(
                f"INSERT INTO {ENCOUNTERS_TABLE} (encounter_id, patient_id, hospital, department, payer, "
                f"admit_date, discharge_date, los_days, is_readmission, attending_physician) VALUES {', '.join(enc_rows)}"
            )
        if ed_rows:
            stmts.append(
                f"INSERT INTO {ED_WAIT_TABLE} (encounter_id, hospital, acuity_level, wait_minutes, arrival_time) VALUES {', '.join(ed_rows)}"
            )
        if drug_rows:
            stmts.append(
                f"INSERT INTO {DRUG_COSTS_TABLE} (encounter_id, drug_name, drug_category, quantity, unit_cost, total_cost, date) VALUES {', '.join(drug_rows)}"
            )
        if staff_rows:
            stmts.append(
                f"INSERT INTO {STAFFING_TABLE} (hospital, department, staff_type, fte_count, date) VALUES {', '.join(staff_rows)}"
            )

        for stmt in stmts:
            _exec_sql(stmt)

        logger.info(f"SEED: Inserted {len(enc_rows)} encounters, {len(ed_rows)} ED waits, "
                     f"{len(drug_rows)} drug costs, {len(staff_rows)} staffing rows")
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
                    event = progress_queue.get(timeout=600)
                except queue.Empty:
                    _deep_tasks[task_id] = {**_deep_tasks[task_id], "status": "error", "error": "Analysis timed out after 10 minutes."}
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
    """Insert anomalous data across all tables -- high LOS, high costs, long ED waits, high contract labor."""
    try:
        import random
        body = request.get_json(silent=True) or {}
        count = max(1, min(1000, int(body.get("count", 30))))
        ts = int(datetime.utcnow().timestamp())
        now = datetime.utcnow()
        hospitals = ["Hospital_A", "Hospital_B", "Hospital_C"]
        depts = ["Cardiology", "Orthopedics", "General_Medicine", "Neurology"]
        enc_rows, ed_rows, drug_rows, staff_rows = [], [], [], []

        for i in range(count):
            eid = f"ANOM_{ts}_{i:03d}"
            hosp = random.choice(hospitals)
            dept = random.choice(depts)
            los = random.randint(10, 25)
            days_ago = random.randint(0, 6)
            admit = (now - timedelta(days=days_ago + los)).strftime("%Y-%m-%d")
            discharge = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            enc_rows.append(
                f"('{eid}', 'PAT_{ts}_{i}', '{hosp}', '{dept}', 'Medicare', "
                f"'{admit}', '{discharge}', {los}, true, 'Dr. Demo')")
            acuity = random.randint(1, 4)
            wait = round(random.uniform(70, 120), 1)
            arrival = (now - timedelta(days=days_ago, hours=random.randint(0, 12))).strftime("%Y-%m-%d %H:%M:%S")
            ed_rows.append(f"('{eid}', '{hosp}', {acuity}, {wait}, TIMESTAMP'{arrival}')")
            for cat, drug, cost in [("Biologics", "Infliximab", random.uniform(800, 2500)),
                                     ("Specialty", "Pembrolizumab", random.uniform(1200, 4000)),
                                     ("Oncology", "Trastuzumab", random.uniform(600, 1800))]:
                d = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                drug_rows.append(f"('{eid}', '{drug}', '{cat}', {random.randint(1,5)}, {round(cost,2)}, {round(cost*random.randint(1,3),2)}, '{d}')")

        for dept in depts:
            for hosp in hospitals:
                d = now.strftime("%Y-%m-%d")
                staff_rows.append(f"('{hosp}', '{dept}', 'contract', {round(random.uniform(20, 40), 1)}, '{d}')")
                staff_rows.append(f"('{hosp}', '{dept}', 'full_time', {round(random.uniform(5, 15), 1)}, '{d}')")

        _exec_sql(f"INSERT INTO {ENCOUNTERS_TABLE} (encounter_id, patient_id, hospital, department, payer, admit_date, discharge_date, los_days, is_readmission, attending_physician) VALUES {', '.join(enc_rows)}")
        _exec_sql(f"INSERT INTO {ED_WAIT_TABLE} (encounter_id, hospital, acuity_level, wait_minutes, arrival_time) VALUES {', '.join(ed_rows)}")
        _exec_sql(f"INSERT INTO {DRUG_COSTS_TABLE} (encounter_id, drug_name, drug_category, quantity, unit_cost, total_cost, date) VALUES {', '.join(drug_rows)}")
        _exec_sql(f"INSERT INTO {STAFFING_TABLE} (hospital, department, staff_type, fte_count, date) VALUES {', '.join(staff_rows)}")
        total = len(enc_rows) + len(ed_rows) + len(drug_rows) + len(staff_rows)
        return jsonify({"success": True, "injected": total, "encounters": len(enc_rows)})
    except Exception as e:
        logger.error(f"Inject anomaly error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/inject-good", methods=["POST"])
@require_demo_mode
def inject_good_data():
    """Insert healthy data across all tables -- short LOS, low costs, fast ED, low contract labor."""
    try:
        import random
        body = request.get_json(silent=True) or {}
        count = max(1, min(1000, int(body.get("count", 30))))
        ts = int(datetime.utcnow().timestamp())
        now = datetime.utcnow()
        hospitals = ["Hospital_A", "Hospital_B", "Hospital_C"]
        depts = ["Cardiology", "Orthopedics", "General_Medicine", "Neurology", "Pediatrics"]
        enc_rows, ed_rows, drug_rows, staff_rows = [], [], [], []

        for i in range(count):
            eid = f"GOOD_{ts}_{i:03d}"
            hosp = random.choice(hospitals)
            dept = random.choice(depts)
            los = round(random.uniform(1, 3.5), 1)
            days_ago = random.randint(0, 6)
            admit = (now - timedelta(days=days_ago + los)).strftime("%Y-%m-%d")
            discharge = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            enc_rows.append(
                f"('{eid}', 'PAT_{ts}_{i}', '{hosp}', '{dept}', 'BlueCross', "
                f"'{admit}', '{discharge}', {los}, false, 'Dr. Good')")
            acuity = random.randint(2, 5)
            wait = round(random.uniform(8, 25), 1)
            arrival = (now - timedelta(days=days_ago, hours=random.randint(0, 12))).strftime("%Y-%m-%d %H:%M:%S")
            ed_rows.append(f"('{eid}', '{hosp}', {acuity}, {wait}, TIMESTAMP'{arrival}')")
            for cat, drug, cost in [("Analgesics", "Ibuprofen", random.uniform(5, 30)),
                                     ("Antibiotics", "Amoxicillin", random.uniform(10, 50))]:
                d = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                drug_rows.append(f"('{eid}', '{drug}', '{cat}', {random.randint(1,10)}, {round(cost,2)}, {round(cost*random.randint(1,2),2)}, '{d}')")

        for dept in depts:
            for hosp in hospitals:
                d = now.strftime("%Y-%m-%d")
                staff_rows.append(f"('{hosp}', '{dept}', 'full_time', {round(random.uniform(25, 45), 1)}, '{d}')")
                staff_rows.append(f"('{hosp}', '{dept}', 'contract', {round(random.uniform(2, 8), 1)}, '{d}')")

        _exec_sql(f"INSERT INTO {ENCOUNTERS_TABLE} (encounter_id, patient_id, hospital, department, payer, admit_date, discharge_date, los_days, is_readmission, attending_physician) VALUES {', '.join(enc_rows)}")
        _exec_sql(f"INSERT INTO {ED_WAIT_TABLE} (encounter_id, hospital, acuity_level, wait_minutes, arrival_time) VALUES {', '.join(ed_rows)}")
        _exec_sql(f"INSERT INTO {DRUG_COSTS_TABLE} (encounter_id, drug_name, drug_category, quantity, unit_cost, total_cost, date) VALUES {', '.join(drug_rows)}")
        _exec_sql(f"INSERT INTO {STAFFING_TABLE} (hospital, department, staff_type, fte_count, date) VALUES {', '.join(staff_rows)}")
        total = len(enc_rows) + len(ed_rows) + len(drug_rows) + len(staff_rows)
        return jsonify({"success": True, "injected": total, "encounters": len(enc_rows)})
    except Exception as e:
        logger.error(f"Inject good data error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/reset", methods=["POST"])
@require_demo_mode
def reset_demo_data():
    """Delete all injected (GOOD_/ANOM_/BFILL_) data and clear analysis_outputs."""
    try:
        _exec_sql(f"DELETE FROM {ENCOUNTERS_TABLE} WHERE encounter_id LIKE 'GOOD_%' OR encounter_id LIKE 'ANOM_%' OR encounter_id LIKE 'BFILL_%'")
        _exec_sql(f"DELETE FROM {ED_WAIT_TABLE} WHERE encounter_id LIKE 'GOOD_%' OR encounter_id LIKE 'ANOM_%' OR encounter_id LIKE 'BFILL_%'")
        _exec_sql(f"DELETE FROM {DRUG_COSTS_TABLE} WHERE encounter_id LIKE 'GOOD_%' OR encounter_id LIKE 'ANOM_%' OR encounter_id LIKE 'BFILL_%'")
        _exec_sql(f"DELETE FROM {STAFFING_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 7 DAYS AND hospital IN ('Hospital_A','Hospital_B','Hospital_C')")
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
        cols, rows = _run_sql(f"SELECT MAX(DATE(admit_date)) FROM {ENCOUNTERS_TABLE}")
        if not rows or not rows[0] or rows[0][0] is None:
            return jsonify({"error": "No existing data to backfill from"}), 400
        last_date = datetime.strptime(str(rows[0][0]), "%Y-%m-%d").date()
        today = datetime.utcnow().date()
        gap_days = (today - last_date).days
        if gap_days <= 0:
            return jsonify({"success": True, "days_filled": 0, "encounters": 0, "message": "Data is already current"})

        hospitals = ["Hospital_A", "Hospital_B", "Hospital_C"]
        depts = ["Cardiology", "Orthopedics", "General_Medicine", "Neurology", "Pediatrics", "Emergency"]
        payers = ["BlueCross", "Medicare", "Aetna", "UnitedHealth", "Cigna"]
        drug_cats = ["Antibiotics", "Analgesics", "Cardiovascular", "Oncology", "Respiratory"]
        drug_names = ["Amoxicillin", "Ibuprofen", "Lisinopril", "Metformin", "Atorvastatin",
                      "Omeprazole", "Amlodipine", "Albuterol", "Gabapentin", "Losartan"]
        staff_types = ["full_time", "contract"]
        ts = int(datetime.utcnow().timestamp())

        enc_rows, ed_rows, drug_rows, staff_rows = [], [], [], []
        enc_count = 0
        staffing_weeks_done = set()

        for day_offset in range(1, gap_days + 1):
            target_date = last_date + timedelta(days=day_offset)
            daily_encounters = random.randint(1, 3)
            for i in range(daily_encounters):
                los = round(random.uniform(1.5, 8.0), 1)
                is_readmit = random.random() < 0.08
                hosp = random.choice(hospitals)
                dept = random.choice(depts)
                admit = (target_date - timedelta(days=int(los))).strftime("%Y-%m-%d")
                discharge = target_date.strftime("%Y-%m-%d")
                eid = f"BFILL_{ts}_{enc_count:04d}"
                enc_rows.append(
                    f"('{eid}', 'PAT_BF_{enc_count}', '{hosp}', '{dept}', '{random.choice(payers)}', "
                    f"'{admit}', '{discharge}', {los}, {str(is_readmit).lower()}, 'Dr. Baseline')"
                )
                if random.random() < 0.6:
                    acuity = random.randint(1, 5)
                    wait = round(random.uniform(5, 90 if acuity > 2 else 30), 1)
                    arrival = f"{target_date} {random.randint(0,23):02d}:{random.randint(0,59):02d}:00"
                    ed_rows.append(f"('{eid}', '{hosp}', {acuity}, {wait}, TIMESTAMP'{arrival}')")
                for _ in range(random.randint(1, 3)):
                    drug = random.choice(drug_names)
                    cat = random.choice(drug_cats)
                    qty = random.randint(1, 30)
                    unit_cost = round(random.uniform(5, 200), 2)
                    total = round(qty * unit_cost, 2)
                    drug_rows.append(f"('{eid}', '{drug}', '{cat}', {qty}, {unit_cost}, {total}, '{target_date}')")
                enc_count += 1

            week_key = target_date.isocalendar()[1]
            if week_key not in staffing_weeks_done:
                staffing_weeks_done.add(week_key)
                for dept in depts:
                    for st in staff_types:
                        fte = round(random.uniform(5, 30), 1)
                        staff_rows.append(f"('{random.choice(hospitals)}', '{dept}', '{st}', {fte}, '{target_date}')")

        if enc_rows:
            for chunk_start in range(0, len(enc_rows), 500):
                chunk = enc_rows[chunk_start:chunk_start + 500]
                _exec_sql(f"INSERT INTO {ENCOUNTERS_TABLE} (encounter_id, patient_id, hospital, department, payer, "
                          f"admit_date, discharge_date, los_days, is_readmission, attending_physician) VALUES {', '.join(chunk)}")
        if ed_rows:
            for chunk_start in range(0, len(ed_rows), 500):
                chunk = ed_rows[chunk_start:chunk_start + 500]
                _exec_sql(f"INSERT INTO {ED_WAIT_TABLE} (encounter_id, hospital, acuity_level, wait_minutes, arrival_time) VALUES {', '.join(chunk)}")
        if drug_rows:
            for chunk_start in range(0, len(drug_rows), 500):
                chunk = drug_rows[chunk_start:chunk_start + 500]
                _exec_sql(f"INSERT INTO {DRUG_COSTS_TABLE} (encounter_id, drug_name, drug_category, quantity, unit_cost, total_cost, date) VALUES {', '.join(chunk)}")
        if staff_rows:
            for chunk_start in range(0, len(staff_rows), 500):
                chunk = staff_rows[chunk_start:chunk_start + 500]
                _exec_sql(f"INSERT INTO {STAFFING_TABLE} (hospital, department, staff_type, fte_count, date) VALUES {', '.join(chunk)}")

        logger.info(f"BACKFILL: Filled {gap_days} days with {enc_count} encounters, {len(ed_rows)} ED, {len(drug_rows)} drugs, {len(staff_rows)} staffing")
        return jsonify({"success": True, "days_filled": gap_days, "encounters": enc_count})
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
        los_query = f"SELECT AVG(los_days) as avg_los FROM {ENCOUNTERS_TABLE} WHERE admit_date > CURRENT_TIMESTAMP - INTERVAL 30 DAYS"
        ed_query = f"SELECT COUNT(*) as breach_count FROM {ED_WAIT_TABLE} WHERE wait_minutes > 60 AND arrival_time > CURRENT_TIMESTAMP - INTERVAL 7 DAYS"
        readmit_query = f"SELECT ROUND(SUM(CASE WHEN is_readmission THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as readmit_rate FROM {ENCOUNTERS_TABLE}"

        _, los_rows = _run_sql(los_query, w)
        _, ed_rows = _run_sql(ed_query, w)
        _, readmit_rows = _run_sql(readmit_query, w)

        avg_los = float(los_rows[0][0]) if los_rows and los_rows[0][0] else None
        ed_breaches = int(ed_rows[0][0]) if ed_rows and ed_rows[0][0] else 0
        readmit_rate = float(readmit_rows[0][0]) if readmit_rows and readmit_rows[0][0] else None

        _, enc_rows = _run_sql(f"SELECT COUNT(*) FROM {ENCOUNTERS_TABLE}", w)
        total_encounters = int(enc_rows[0][0] or 0) if enc_rows else 0

        if total_encounters == 0 or avg_los is None:
            return jsonify({"score": None, "avg_los": 0, "readmission_rate": 0, "ed_breaches": 0,
                            "total_encounters": total_encounters,
                            "summary": "No encounter data available. Run generate_data or use Inject buttons."})

        r_rate = readmit_rate or 0.0
        los_score = max(0, min(40, 40 - (avg_los - 4.0) * 10))
        readmit_score = max(0, min(30, 30 - (r_rate - 5.0) * 3))
        ed_score = max(0, min(30, 30 - ed_breaches * 0.5))
        health_score = max(0, min(100, int(los_score + readmit_score + ed_score)))

        summary = f"{total_encounters} encounters tracked, avg LOS {avg_los:.1f} days. "
        if health_score >= 80:
            summary += "Operations running well."
        elif health_score >= 60:
            summary += "Some attention needed."
        else:
            summary += "Critical issues detected."

        _health_score_history.append({"score": health_score, "ts": datetime.utcnow().isoformat()})
        if len(_health_score_history) > 50:
            _health_score_history[:] = _health_score_history[-50:]

        return jsonify({"score": health_score, "avg_los": round(avg_los, 1), "readmission_rate": round(r_rate, 1),
                        "ed_breaches": ed_breaches, "total_encounters": total_encounters, "summary": summary})
    except Exception as e:
        logger.error(f"Health score error: {e}", exc_info=True)
        return jsonify({"score": None, "error": str(e)}), 200


@app.route("/api/alerts/active", methods=["GET"])
def get_alerts():
    try:
        w = get_workspace_client()
        query = f"""
        SELECT hospital, department, ROUND(AVG(los_days), 1) as avg_los, COUNT(*) as enc_count
        FROM {ENCOUNTERS_TABLE}
        WHERE admit_date > CURRENT_TIMESTAMP - INTERVAL 7 DAYS
        GROUP BY hospital, department
        HAVING AVG(los_days) > 6.0
        ORDER BY avg_los DESC LIMIT 5
        """
        cols, rows = _run_sql(query, w)
        alerts = []
        if rows:
            for row in rows:
                data = dict(zip(cols, row))
                avg_los = float(data.get("avg_los", 0) or 0)
                alerts.append({
                    "id": f"los_{data['hospital']}_{data['department']}",
                    "severity": "high" if avg_los > 8 else "medium",
                    "title": f"High LOS: {data['hospital']} / {data['department']}",
                    "detail": f"Avg {avg_los} days across {data.get('enc_count', 0)} encounters this week"
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
RECOMMENDED ACTIONS REPORT
{'='*60}

Recommendation ID: {rec['id']}
Encounter ID: {rec.get('encounter_id', 'N/A')}
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
Administrator Signature: ______________________  Date: __________
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
    try:
        w = get_workspace_client()
        query = f"""SELECT acuity_level,
            ROUND(AVG(wait_minutes), 1) as avg_wait,
            COUNT(*) as total,
            SUM(CASE WHEN (acuity_level <= 2 AND wait_minutes > 15) OR (acuity_level > 2 AND wait_minutes > 60) THEN 1 ELSE 0 END) as breaches
        FROM {ED_WAIT_TABLE}
        WHERE arrival_time >= CURRENT_TIMESTAMP - INTERVAL 30 DAYS
        GROUP BY acuity_level ORDER BY acuity_level"""
        cols, rows = _run_sql(query, w)
        levels = []
        total_breaches = 0
        for row in rows:
            d = dict(zip(cols, row))
            b = int(d.get("breaches") or 0)
            total_breaches += b
            levels.append({"acuity": int(d.get("acuity_level", 0)),
                           "avg_wait": float(d.get("avg_wait") or 0),
                           "total": int(d.get("total") or 0), "breaches": b})
        return jsonify({"levels": levels, "total_breaches": total_breaches})
    except Exception as e:
        return jsonify({"error": str(e), "levels": [], "total_breaches": 0}), 200


@app.route("/api/drugs/summary", methods=["GET"])
def get_drugs_summary():
    try:
        w = get_workspace_client()
        total_q = f"SELECT ROUND(SUM(total_cost), 2) as total_spend FROM {DRUG_COSTS_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS"
        cat_q = f"""SELECT drug_category, ROUND(SUM(total_cost), 2) as spend
            FROM {DRUG_COSTS_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS
            GROUP BY drug_category ORDER BY spend DESC LIMIT 3"""
        _, total_rows = _run_sql(total_q, w)
        cat_cols, cat_rows = _run_sql(cat_q, w)
        total_spend = float(total_rows[0][0] or 0) if total_rows else 0
        categories = []
        for row in cat_rows:
            d = dict(zip(cat_cols, row))
            categories.append({"category": d.get("drug_category"), "spend": float(d.get("spend") or 0)})
        return jsonify({"total_spend": total_spend, "categories": categories})
    except Exception as e:
        return jsonify({"error": str(e), "total_spend": 0, "categories": []}), 200


@app.route("/api/staffing/summary", methods=["GET"])
def get_staffing_summary():
    try:
        w = get_workspace_client()
        query = f"""SELECT department,
            ROUND(SUM(CASE WHEN staff_type = 'contract' THEN fte_count ELSE 0 END) * 100.0 /
                  NULLIF(SUM(fte_count), 0), 1) as contract_pct,
            SUM(fte_count) as total_fte
        FROM {STAFFING_TABLE}
        WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS
        GROUP BY department ORDER BY contract_pct DESC"""
        cols, rows = _run_sql(query, w)
        departments = []
        overall_contract = 0
        overall_total = 0
        for row in rows:
            d = dict(zip(cols, row))
            pct = float(d.get("contract_pct") or 0)
            fte = int(d.get("total_fte") or 0)
            overall_contract += pct * fte / 100
            overall_total += fte
            departments.append({"department": d.get("department"), "contract_pct": pct, "total_fte": fte})
        overall_pct = round(overall_contract / overall_total * 100, 1) if overall_total else 0
        return jsonify({"overall_contract_pct": overall_pct, "departments": departments[:5]})
    except Exception as e:
        return jsonify({"error": str(e), "overall_contract_pct": 0, "departments": []}), 200


@app.route("/api/encounters/summary", methods=["GET"])
def get_encounter_summary():
    try:
        w = get_workspace_client()
        query = f"""SELECT COUNT(*) as total_encounters,
               SUM(CASE WHEN is_readmission THEN 1 ELSE 0 END) as readmissions,
               COUNT(DISTINCT hospital) as hospital_count,
               ROUND(AVG(los_days), 1) as avg_los
        FROM {ENCOUNTERS_TABLE}"""
        trend_query = f"""SELECT
            ROUND(AVG(CASE WHEN admit_date > CURRENT_TIMESTAMP - INTERVAL 7 DAYS THEN los_days END), 2) as this_week_los,
            ROUND(AVG(CASE WHEN admit_date BETWEEN CURRENT_TIMESTAMP - INTERVAL 14 DAYS AND CURRENT_TIMESTAMP - INTERVAL 7 DAYS THEN los_days END), 2) as last_week_los,
            SUM(CASE WHEN admit_date > CURRENT_TIMESTAMP - INTERVAL 7 DAYS AND is_readmission THEN 1 ELSE 0 END) as this_week_readmits,
            SUM(CASE WHEN admit_date BETWEEN CURRENT_TIMESTAMP - INTERVAL 14 DAYS AND CURRENT_TIMESTAMP - INTERVAL 7 DAYS AND is_readmission THEN 1 ELSE 0 END) as last_week_readmits,
            SUM(CASE WHEN admit_date > CURRENT_TIMESTAMP - INTERVAL 7 DAYS THEN 1 ELSE 0 END) as this_week_enc,
            SUM(CASE WHEN admit_date BETWEEN CURRENT_TIMESTAMP - INTERVAL 14 DAYS AND CURRENT_TIMESTAMP - INTERVAL 7 DAYS THEN 1 ELSE 0 END) as last_week_enc
        FROM {ENCOUNTERS_TABLE}
        WHERE admit_date > CURRENT_TIMESTAMP - INTERVAL 14 DAYS"""
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
                if lw_los > 0:
                    trends["los_trend"] = round((tw_los - lw_los) / lw_los * 100, 1)
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
    try:
        w = get_workspace_client()
        query = f"""SELECT hospital, COUNT(*) as encounter_count,
               SUM(CASE WHEN is_readmission THEN 1 ELSE 0 END) as readmission_count,
               ROUND(AVG(los_days), 1) as avg_los
        FROM {ENCOUNTERS_TABLE} GROUP BY hospital ORDER BY hospital"""
        cols, rows = _run_sql(query, w)
        data = [dict(zip(cols, row)) for row in rows]
        return jsonify({"hospital_stats": data})
    except Exception as e:
        return jsonify({"error": str(e), "hospital_stats": []}), 200


@app.route("/api/encounters/by-department", methods=["GET"])
def get_encounters_by_department():
    try:
        w = get_workspace_client()
        query = f"""SELECT department, COUNT(*) as encounter_count,
               SUM(CASE WHEN is_readmission THEN 1 ELSE 0 END) as readmission_count,
               ROUND(AVG(los_days), 1) as avg_los
        FROM {ENCOUNTERS_TABLE} GROUP BY department ORDER BY encounter_count DESC"""
        cols, rows = _run_sql(query, w)
        data = [dict(zip(cols, row)) for row in rows]
        return jsonify({"department_stats": data})
    except Exception as e:
        return jsonify({"error": str(e), "department_stats": []}), 200


@app.route("/api/encounters/timeline", methods=["GET"])
def get_encounters_timeline():
    try:
        w = get_workspace_client()
        days = request.args.get("days", 30, type=int)
        query = f"""SELECT DATE(admit_date) as encounter_date, COUNT(*) as encounter_count,
               SUM(CASE WHEN is_readmission THEN 1 ELSE 0 END) as readmission_count
        FROM {ENCOUNTERS_TABLE} WHERE admit_date >= CURRENT_DATE - INTERVAL {days} DAYS
        GROUP BY DATE(admit_date) ORDER BY encounter_date ASC"""
        cols, rows = _run_sql(query, w)
        timeline = []
        for row in rows:
            data = dict(zip(cols, row))
            timeline.append({"date": str(data.get("encounter_date")),
                             "encounters": int(data.get("encounter_count", 0) or 0),
                             "readmissions": int(data.get("readmission_count", 0) or 0)})
        return jsonify({"timeline": timeline, "days": days})
    except Exception as e:
        return jsonify({"error": str(e), "timeline": []}), 200


@app.route("/api/encounters/readmissions", methods=["GET"])
def get_readmissions():
    try:
        w = get_workspace_client()
        limit = request.args.get("limit", 5, type=int)
        query = f"""SELECT e.encounter_id, e.hospital, e.department, e.los_days,
            e.admit_date, e.discharge_date, e.payer,
            COALESCE(d.total_drug_cost, 0) as total_drug_cost
        FROM {ENCOUNTERS_TABLE} e
        LEFT JOIN (
            SELECT encounter_id, ROUND(SUM(total_cost), 2) as total_drug_cost
            FROM {DRUG_COSTS_TABLE} GROUP BY encounter_id
        ) d ON e.encounter_id = d.encounter_id
        WHERE e.is_readmission = true
        ORDER BY e.admit_date DESC LIMIT {limit}"""
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
    try:
        w = get_workspace_client()
        query = f"""SELECT department, ROUND(AVG(los_days), 1) as avg_los, COUNT(*) as enc_count
            FROM {ENCOUNTERS_TABLE} WHERE admit_date >= CURRENT_DATE - INTERVAL 30 DAYS
            GROUP BY department ORDER BY avg_los DESC"""
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
    try:
        w = get_workspace_client()
        query = f"""SELECT payer, COUNT(*) as enc_count
            FROM {ENCOUNTERS_TABLE} WHERE admit_date >= CURRENT_DATE - INTERVAL 30 DAYS
            GROUP BY payer ORDER BY enc_count DESC LIMIT 6"""
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
    """Return context-aware suggested questions based on current data conditions."""
    suggestions = []
    try:
        w = get_workspace_client()
        _, los_rows = _run_sql(f"SELECT AVG(los_days) FROM {ENCOUNTERS_TABLE} WHERE admit_date > CURRENT_TIMESTAMP - INTERVAL 30 DAYS", w)
        avg_los = float(los_rows[0][0] or 0) if los_rows and los_rows[0][0] else 0
        _, re_rows = _run_sql(f"SELECT ROUND(SUM(CASE WHEN is_readmission THEN 1 ELSE 0 END)*100.0/NULLIF(COUNT(*),0),1) FROM {ENCOUNTERS_TABLE}", w)
        readmit_rate = float(re_rows[0][0] or 0) if re_rows and re_rows[0][0] else 0
        _, ed_rows = _run_sql(f"SELECT COUNT(*) FROM {ED_WAIT_TABLE} WHERE wait_minutes > 60 AND arrival_time > CURRENT_TIMESTAMP - INTERVAL 7 DAYS", w)
        ed_breaches = int(ed_rows[0][0] or 0) if ed_rows and ed_rows[0][0] else 0
        _, contract_rows = _run_sql(f"""SELECT department, ROUND(SUM(CASE WHEN staff_type='contract' THEN fte_count ELSE 0 END)*100.0/NULLIF(SUM(fte_count),0),1) as pct
            FROM {STAFFING_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 30 DAYS GROUP BY department HAVING pct > 30 ORDER BY pct DESC LIMIT 1""", w)
        high_contract_dept = contract_rows[0][0] if contract_rows else None

        if readmit_rate > 10:
            suggestions.append({"label": f"Root cause: Why are {readmit_rate}% of patients readmitted?",
                                "query": f"The 30-day readmission rate is {readmit_rate}%. Analyze root causes by department and payer, and recommend specific interventions grounded in our SOPs."})
        if avg_los > 5:
            suggestions.append({"label": f"Action plan: Reduce LOS from {avg_los:.1f} to target 5 days",
                                "query": f"Average length of stay is {avg_los:.1f} days, above the 5-day target. Which departments are the biggest contributors? What SOP-backed actions can bring it down?"})
        if ed_breaches > 3:
            suggestions.append({"label": f"Investigate: {ed_breaches} patients waited 60+ min in ED",
                                "query": f"We had {ed_breaches} ED wait-time breaches (>60 min) this week. Break down by hospital and acuity level, identify bottlenecks, and recommend fixes."})
        if high_contract_dept:
            suggestions.append({"label": f"Cost control: {high_contract_dept} contract labor above 30%",
                                "query": f"Contract labor in {high_contract_dept} exceeds 30% of total FTEs. What's driving reliance on contract staff, and what's the plan to reduce it?"})
        _, cost_rows = _run_sql(f"SELECT ROUND(SUM(total_cost),0) FROM {DRUG_COSTS_TABLE} WHERE date >= CURRENT_DATE - INTERVAL 7 DAYS", w)
        week_cost = float(cost_rows[0][0] or 0) if cost_rows and cost_rows[0][0] else 0
        if week_cost > 50000:
            suggestions.append({"label": f"Spend alert: ${week_cost/1000:.0f}k drug costs this week",
                                "query": f"Drug costs hit ${week_cost:,.0f} this week. Which drug categories and hospitals are driving the increase? Are there formulary alternatives?"})

        fallbacks = [
            {"label": "Top 3 actions for hospital leadership this week",
             "query": "Based on all current operations data, what are the top 3 next best actions hospital leadership should take this week? Prioritize by impact."},
            {"label": "Compare ED performance across all hospitals",
             "query": "Compare Emergency Department wait times, breach rates, and throughput across Hospital A, B, and C. Which hospital is performing best and why?"},
            {"label": "Which departments have highest readmission risk?",
             "query": "Analyze readmission risk by department. Which departments have the highest readmission rates, and what patient or operational factors are correlated?"},
            {"label": "What do SOPs say about reducing surgical LOS?",
             "query": "Search our standard operating procedures for guidance on reducing length of stay for surgical patients. Summarize the key protocols."},
            {"label": "Create a staffing optimization plan",
             "query": "Analyze current staffing patterns across hospitals. Where is contract labor highest? Create a quarterly plan to optimize the full-time to contract ratio."},
        ]
        for fb in fallbacks:
            if len(suggestions) >= 5:
                break
            suggestions.append(fb)
    except Exception as e:
        logger.warning(f"Suggestions error: {e}")
        suggestions = [
            {"label": "Top 3 actions for hospital leadership this week",
             "query": "Based on current operations data, what are the top 3 next best actions hospital leadership should take this week?"},
            {"label": "Compare ED performance across all hospitals",
             "query": "Compare ED wait times and breach rates across Hospital A, B, and C."},
            {"label": "What do SOPs say about reducing surgical LOS?",
             "query": "Search our SOPs for guidance on reducing length of stay for surgical patients."},
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
