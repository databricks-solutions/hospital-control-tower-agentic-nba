"""Autonomous agent scheduler - proactive monitoring and learning."""
import os
import random
import logging
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Dict, Any
from dataclasses import dataclass
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = int(os.environ.get("AUTONOMOUS_INTERVAL_SECONDS", "3600"))
DEFAULT_MAX_RUNTIME = int(os.environ.get("AUTONOMOUS_MAX_RUNTIME_SECONDS", "7200"))
MIN_INTERVAL = 60
MAX_INTERVAL = 86400


@dataclass
class AutonomousCapability:
    id: str
    name: str
    weight: int
    prompt: str
    enabled: bool = True


CAPABILITIES = [
    AutonomousCapability(
        id="cost_monitoring",
        name="Drug Cost Monitoring",
        weight=20,
        prompt="""Monitor drug costs across hospitals for anomalies and spikes.

1. Query fact_drug_costs for the last 30 days, grouped by hospital and drug_category
2. Compare current month spend to previous months - flag any >30% increases
3. Identify top 10 highest-cost drugs and check for unit cost outliers
4. Check fact_operational_kpis for drug_cost_per_encounter trends by hospital

MUST use search_sops to find cost management procedures:
- "pharmacy cost control procedures"
- "drug formulary management"
- "high-cost drug approval protocols"

Generate report with:
- Hospitals with cost anomalies
- Specific drugs driving cost increases
- SOP-grounded recommendations for cost containment

FORMATTING: Use markdown. Each recommendation on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'cost_monitoring'.""",
    ),
    AutonomousCapability(
        id="los_analysis",
        name="Length of Stay Analysis",
        weight=25,
        prompt="""Analyze length of stay patterns and identify reduction opportunities.

1. Query dim_encounters for LOS by hospital, department, and discharge day of week
2. Identify departments with avg LOS > 5.0 days
3. Analyze the Monday discharge effect - compare Monday LOS to other days
4. Check readmission rates for correlation with short LOS (premature discharge)
5. Compare Hospital_A LOS to Hospital_B and Hospital_C

MUST use search_sops FIRST for discharge planning procedures:
- "discharge planning protocols"
- "length of stay reduction"
- "care coordination procedures"
- "weekend discharge procedures"

Generate report with:
- LOS by hospital with benchmarks
- Day-of-week discharge patterns
- Top 3 departments with improvement opportunities
- CAPA recommendations citing specific SOPs

FORMATTING: Use markdown. Each recommendation on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'los_analysis'.""",
    ),
    AutonomousCapability(
        id="ed_performance",
        name="ED Performance Monitoring",
        weight=15,
        prompt="""Monitor Emergency Department performance and wait times.

1. Query fact_ed_wait_times for average wait by acuity level
2. Check threshold breaches: >15 min for acuity 1-2, >60 min for acuity 3-5
3. Identify time-of-day and day-of-week patterns
4. Compare ED performance across hospitals

MUST use search_sops for ED flow procedures:
- "ED throughput protocols"
- "triage procedures"
- "patient flow management"

Generate report with:
- Wait times by acuity with threshold status
- Breach frequency and patterns
- Specific recommendations for wait time reduction

FORMATTING: Use markdown. Each recommendation on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'ed_performance'.""",
    ),
    AutonomousCapability(
        id="staffing_optimization",
        name="Staffing Optimization",
        weight=15,
        prompt="""Analyze staffing patterns and contract labor efficiency.

1. Query fact_staffing for contract labor percentage by department
2. Identify departments where contract labor > 25% of total FTEs
3. Calculate cost differential: contract vs full-time per department
4. Check trends - is contract labor increasing?

MUST use search_sops for staffing procedures:
- "workforce planning"
- "contract labor management"
- "staffing ratio requirements"

Generate report with:
- Departments ranked by contract labor percentage
- Cost impact analysis
- Recruitment vs contract labor ROI
- SOP-grounded recommendations for reducing contract reliance

FORMATTING: Use markdown. Each recommendation on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'staffing_analysis'.""",
    ),
    AutonomousCapability(
        id="next_best_action_report",
        name="Next Best Action Report",
        weight=20,
        prompt="""Synthesize monitoring and analysis into prioritized actionable report.

STEP 1 - Check prerequisites:
   - Query analysis_outputs for analyses in the last 24 hours:
     SELECT analysis_type, MAX(created_at) as last_run FROM analysis_outputs
     WHERE created_at >= current_timestamp() - INTERVAL 24 HOURS GROUP BY analysis_type
   - Required types: cost_monitoring, los_analysis, ed_performance, staffing_analysis
   - For each MISSING analysis, run it now using the appropriate tools:
     * cost_monitoring missing -> analyze_cost_drivers for each hospital
     * los_analysis missing -> analyze_los_factors for each hospital
     * ed_performance missing -> check_ed_performance for each hospital
     * staffing_analysis missing -> check_staffing_efficiency for each hospital
   - Save each prerequisite result with write_analysis before proceeding.

STEP 2 - Gather recent findings:
   - Query analysis_outputs for all findings in last 24 hours
   - Identify critical issues and recurring patterns

STEP 3 - Ground with SOPs:
   - search_sops: "operational improvement procedures"
   - search_sops: "quality improvement protocols"
   - search_sops: "patient safety procedures"

STEP 4 - Generate prioritized report using markdown formatting:

**CRITICAL** (immediate, within 4 hours)

1. Action description -- SOP: ... Expected outcome: ... Risk if delayed: ...

2. Next action...

**HIGH PRIORITY** (within 24 hours)

3. Action description...

**MEDIUM PRIORITY** (within week)

4. Action description...

Each action MUST be on its own numbered line with a blank line between items.
Start with a 2-3 sentence executive summary before the priority sections.

Save using write_analysis with type 'next_best_action_report' and priority field set.""",
    ),
    AutonomousCapability(
        id="readiness_check",
        name="Operations Readiness Check",
        weight=15,
        prompt="""Check analysis freshness and run any stale or missing analyses to prepare
for user-driven Next Best Action requests.

1. Query analysis_outputs for the most recent run of each type:
   SELECT analysis_type, MAX(created_at) as last_run
   FROM analysis_outputs GROUP BY analysis_type

2. For each of these required types, if missing or older than 24 hours, run the analysis:
   - cost_monitoring: use analyze_cost_drivers for all hospitals
   - los_analysis: use analyze_los_factors for all hospitals
   - ed_performance: use check_ed_performance for all hospitals
   - staffing_analysis: use check_staffing_efficiency for all hospitals
   - compliance_monitoring: use check_operational_kpis for all hospitals

3. For each analysis you run, save the result with write_analysis.

4. After all prerequisite analyses are current, log a summary of what was refreshed.

FORMATTING: Use markdown. Each finding on its own numbered line with a blank line between items. Use **bold** for section headings.

Save a summary using write_analysis with type 'readiness_check'.""",
    ),
    AutonomousCapability(
        id="compliance_monitoring",
        name="Compliance Monitoring",
        weight=5,
        prompt="""Check operational KPIs against accreditation and regulatory thresholds.

Query fact_operational_kpis for trends in:
- avg_los (target: <5.0 days)
- readmission_rate (target: <10%)
- bed_utilization_pct (target: 75-85%)
- contract_labor_pct (target: <25%)
- avg_ed_wait_minutes (target: <60 min)

For each KPI:
1. Get current value and 30-day trend
2. Calculate days until threshold breach if trending negatively
3. Compare across hospitals

FORMATTING: Use markdown. Each finding on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'compliance_monitoring'.""",
    ),
]


class AutonomousScheduler:
    def __init__(self, interval_seconds: int = DEFAULT_INTERVAL,
                 max_runtime_seconds: int = DEFAULT_MAX_RUNTIME):
        self.interval = max(MIN_INTERVAL, min(MAX_INTERVAL, interval_seconds))
        self.max_runtime = max_runtime_seconds
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        self._started_at: Optional[datetime] = None
        self._auto_stop_at: Optional[datetime] = None
        self.last_execution: Optional[datetime] = None
        self.last_capability: Optional[str] = None
        self.execution_count = 0
        self._paused = False
        self._callbacks: List[Callable] = []
        self.capabilities_config = {c.id: c.enabled for c in CAPABILITIES}

    def add_callback(self, callback: Callable):
        self._callbacks.append(callback)

    def set_interval(self, seconds: int):
        self.interval = max(MIN_INTERVAL, min(MAX_INTERVAL, seconds))
        if self.is_running:
            self.stop()
            self.start()

    def set_capabilities(self, config: Dict[str, bool]):
        self.capabilities_config.update(config)

    def _get_capability(self, cap_id: str) -> Optional[AutonomousCapability]:
        return next((c for c in CAPABILITIES if c.id == cap_id), None)

    def _execute_capability(self, capability: AutonomousCapability) -> Dict[str, Any]:
        logger.info(f"Autonomous executing: {capability.name}")
        try:
            from .graph import invoke_agent
            result = invoke_agent(message=capability.prompt, mode="rag")
            self.last_execution = datetime.utcnow()
            self.last_capability = capability.id
            self.execution_count += 1
            for callback in self._callbacks:
                try:
                    callback({"capability": capability.id, "name": capability.name,
                              "timestamp": self.last_execution.isoformat(), "success": True})
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            return {"success": True, "capability": capability.id, "result": result}
        except Exception as e:
            logger.error(f"Autonomous error in {capability.name}: {e}")
            return {"success": False, "capability": capability.id, "error": str(e)}

    def run_health_check(self) -> Dict[str, Any]:
        """Run only the health check capability (for manual trigger)."""
        cap = self._get_capability("readiness_check") or CAPABILITIES[0]
        return self._execute_capability(cap)

    def _autonomous_job(self):
        """Smart workflow: health check first, action report only if issues detected."""
        if self._paused:
            return
        logger.info("Autonomous scheduled run: starting health check")
        health = self._execute_capability(
            self._get_capability("readiness_check") or CAPABILITIES[0]
        )
        response_text = str(health.get("result", {}).get("response", ""))
        issue_signals = ["breach", "exceed", "anomal", "spike", "critical", "warning",
                         "attention", "above threshold", "below target", "degraded"]
        has_issues = any(s in response_text.lower() for s in issue_signals)
        if has_issues:
            logger.info("Health issues detected -- generating action report")
            nba_cap = self._get_capability("next_best_action_report")
            if nba_cap:
                self._execute_capability(nba_cap)
        else:
            logger.info("No health issues found -- skipping action report")

    def _auto_stop(self):
        logger.info(f"Autonomous max runtime ({self.max_runtime}s) reached -- auto-stopping")
        self.stop()

    def start(self):
        if self.is_running:
            return
        self._started_at = datetime.utcnow()
        self._auto_stop_at = self._started_at + timedelta(seconds=self.max_runtime)
        self.scheduler.add_job(self._autonomous_job, trigger=IntervalTrigger(seconds=self.interval),
                               id="autonomous_job", replace_existing=True)
        self.scheduler.add_job(self._auto_stop, trigger='date',
                               run_date=self._auto_stop_at,
                               id="auto_stop_job", replace_existing=True)
        self.scheduler.start()
        self.is_running = True
        logger.info(f"Autonomous mode started with {self.interval}s interval, auto-stop at {self._auto_stop_at.isoformat()}")

    def stop(self):
        if not self.is_running:
            return
        self.scheduler.shutdown(wait=False)
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        self._started_at = None
        self._auto_stop_at = None
        logger.info("Autonomous mode stopped")

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def trigger_now(self, capability_id: Optional[str] = None) -> Dict[str, Any]:
        if capability_id:
            for cap in CAPABILITIES:
                if cap.id == capability_id:
                    return self._execute_capability(cap)
            raise ValueError(f"Unknown capability: {capability_id}")
        return self._autonomous_job()

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running, "is_paused": self._paused,
            "interval_seconds": self.interval,
            "max_runtime_seconds": self.max_runtime,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "auto_stop_at": self._auto_stop_at.isoformat() if self._auto_stop_at else None,
            "last_execution": self.last_execution.isoformat() if self.last_execution else None,
            "last_capability": self.last_capability, "execution_count": self.execution_count,
            "capabilities": [{"id": c.id, "name": c.name, "weight": c.weight,
                              "enabled": self.capabilities_config.get(c.id, True)} for c in CAPABILITIES],
        }


_autonomous: Optional[AutonomousScheduler] = None


def get_autonomous() -> AutonomousScheduler:
    global _autonomous
    if _autonomous is None:
        _autonomous = AutonomousScheduler()
    return _autonomous


def start_autonomous():
    get_autonomous().start()


def stop_autonomous():
    if _autonomous:
        _autonomous.stop()
