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
        id="performance_monitoring",
        name="Fund Performance Monitoring",
        weight=20,
        prompt="""Monitor fund returns, NAV trends, alpha generation, and underperforming funds.

1. Query fact_fund_performance for the last 30 days, grouped by fund and benchmark
2. Compare current period returns to previous periods - flag any >20% underperformance vs benchmark
3. Identify top 10 underperforming funds and check for alpha outliers
4. Check fact_fund_performance for NAV trends and benchmark spread by fund

MUST use search_investment_policies to find performance monitoring procedures:
- "underperformance thresholds and watchlist criteria"
- "benchmark composite construction and attribution"
- "performance escalation protocol levels"

Generate report with:
- Funds with performance anomalies, citing specific IPS thresholds (e.g., >300bps underperformance = Watch, >500bps = Review)
- Specific drivers of underperformance using attribution framework
- Policy-grounded recommendations referencing IPS section numbers

FORMATTING: Use markdown. Each recommendation on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'performance_monitoring'.""",
    ),
    AutonomousCapability(
        id="concentration_analysis",
        name="Portfolio Concentration Analysis",
        weight=25,
        prompt="""Analyze position concentration, top-5 fund concentration, and sector/geography concentration.

1. Query fact_portfolio_holdings for concentration by fund, sector, and geography
2. Identify portfolios where top-5 fund concentration > 40%
3. Analyze sector concentration - flag any sector > 30% of portfolio
4. Check geography concentration for regional overexposure
5. Compare concentration across funds and time periods

MUST use search_investment_policies FIRST for allocation guidelines:
- "single manager concentration limit and top-5 GP exposure"
- "sector concentration limits within healthcare"
- "geographic allocation targets and maximum single country exposure"
- "vintage year diversification and single-position limits"

Generate report with:
- Concentration by fund vs IPS Section 3 limits (single GP max 8% NAV, top-5 max 30%)
- Sector exposure vs sub-sector targets (e.g., biopharma 25-35%, medtech 15-25%)
- Geographic exposure vs limits (US max 65%, single non-US country max 15%)
- Policy-grounded recommendations citing specific IPS section numbers

FORMATTING: Use markdown. Each recommendation on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'concentration_analysis'.""",
    ),
    AutonomousCapability(
        id="flow_analysis",
        name="Fund Flow Analysis",
        weight=15,
        prompt="""Monitor capital calls, distributions, net flows, and liquidity.

1. Query fact_fund_flows for capital calls and distributions by fund
2. Check net flow trends - flag negative flows > 10% of AUM
3. Identify liquidity stress: call coverage ratios, distribution timing
4. Compare flow patterns across funds and time periods

MUST use search_investment_policies for liquidity procedures:
- "liquidity tier classification framework and minimum Tier 1 reserve"
- "capital call notice period and overcommitment ratio limits"
- "distribution waterfall and reinvestment vs payout policy"
- "liquidity alert levels green yellow red"

Generate report with:
- Flow metrics by fund with status vs IPS thresholds (Tier 1 min 7% NAV, overcommitment max 35%)
- Liquidity stress indicators and current alert level
- Capital call forecast vs commitment reserves (IPS requires 40% coverage of 24-month calls)
- Policy-grounded recommendations referencing IPS section numbers

FORMATTING: Use markdown. Each recommendation on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'flow_analysis'.""",
    ),
    AutonomousCapability(
        id="exposure_analysis",
        name="Exposure Shift Analysis",
        weight=15,
        prompt="""Analyze sector/geography exposure changes and style drift.

1. Query fact_portfolio_holdings for exposure by sector and geography over time
2. Identify funds with sector exposure shifts > 5% month-over-month
3. Calculate style drift: compare current allocation to policy targets
4. Check geography exposure trends - flag material shifts

MUST use search_investment_policies for allocation procedures:
- "strategic allocation targets and tactical ranges by strategy"
- "rebalancing trigger bands and protocol timeline"
- "2026 outlook tactical tilts and deployment priorities"

Generate report with:
- Actual allocation vs IPS Section 3.1 targets and tactical ranges
- Style drift: current vs target with trigger band status (e.g., PE target 28%, range 20-36%)
- 2026 tactical tilt compliance: VC overweight +3%, credit underweight -2%
- Policy-grounded rebalancing recommendations with IPS section references

FORMATTING: Use markdown. Each recommendation on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'exposure_analysis'.""",
    ),
    AutonomousCapability(
        id="investment_action_report",
        name="Investment Action Report",
        weight=20,
        prompt="""Synthesize monitoring and analysis into prioritized investment action report.

STEP 1 - Check prerequisites:
   - Query analysis_outputs for analyses in the last 24 hours:
     SELECT analysis_type, MAX(created_at) as last_run FROM analysis_outputs
     WHERE created_at >= current_timestamp() - INTERVAL 24 HOURS GROUP BY analysis_type
   - Required types: performance_monitoring, concentration_analysis, flow_analysis, exposure_analysis
   - For each MISSING analysis, run it now using the appropriate tools:
     * performance_monitoring missing -> analyze_performance_drivers for each fund
     * concentration_analysis missing -> analyze_concentration for each fund
     * flow_analysis missing -> check_fund_flows for each fund
     * exposure_analysis missing -> check_exposure_shifts for each fund
   - Save each prerequisite result with write_analysis before proceeding.

STEP 2 - Gather recent findings:
   - Query analysis_outputs for all findings in last 24 hours
   - Identify critical issues and recurring patterns

STEP 3 - Ground with policies:
   - search_investment_policies: "2026 outlook objectives and tactical tilts"
   - search_investment_policies: "risk escalation matrix severity levels and actions"
   - search_investment_policies: "underperformance thresholds and watchlist escalation protocol"

STEP 4 - Generate prioritized report using markdown formatting:

**CRITICAL** (immediate, within 4 hours)

1. Action description -- Policy: ... Expected outcome: ... Risk if delayed: ...

2. Next action...

**HIGH PRIORITY** (within 24 hours)

3. Action description...

**MEDIUM PRIORITY** (within week)

4. Action description...

Each action MUST be on its own numbered line with a blank line between items.
Start with a 2-3 sentence executive summary before the priority sections.

Save using write_analysis with type 'investment_action_report' and priority field set.""",
    ),
    AutonomousCapability(
        id="portfolio_readiness",
        name="Portfolio Readiness Check",
        weight=15,
        prompt="""Check analysis freshness and run any stale or missing analyses to prepare
for user-driven Investment Action requests.

1. Query analysis_outputs for the most recent run of each type:
   SELECT analysis_type, MAX(created_at) as last_run
   FROM analysis_outputs GROUP BY analysis_type

2. For each of these required types, if missing or older than 24 hours, run the analysis:
   - performance_monitoring: use analyze_performance_drivers for all funds
   - concentration_analysis: use analyze_concentration for all funds
   - flow_analysis: use check_fund_flows for all funds
   - exposure_analysis: use check_exposure_shifts for all funds
   - policy_compliance: use check_portfolio_kpis for all funds

3. For each analysis you run, save the result with write_analysis.

4. After all prerequisite analyses are current, log a summary of what was refreshed.

FORMATTING: Use markdown. Each finding on its own numbered line with a blank line between items. Use **bold** for section headings.

Save a summary using write_analysis with type 'portfolio_readiness'.""",
    ),
    AutonomousCapability(
        id="policy_compliance",
        name="Investment Policy Compliance",
        weight=5,
        prompt="""Check portfolio KPIs against IPS thresholds.

MUST use search_investment_policies FIRST:
- "concentration risk single manager limit and top-5 exposure"
- "liquidity tier minimum reserves"
- "VaR limits and stress test action triggers"

Query fact_portfolio_kpis for trends in:
- concentration_top5_pct (IPS: top-5 GP max 30% NAV; single GP max 8%)
- benchmark_spread (IPS: >200bps underperformance over 3yr triggers IC review)
- total_aum trends

For each KPI:
1. Get current value and 30-day trend
2. Compare to specific IPS threshold and cite section number
3. Calculate days until threshold breach if trending negatively
4. Classify severity per IPS escalation matrix (Severity 1/2/3)

FORMATTING: Use markdown. Each finding on its own numbered line with a blank line between items. Use **bold** for section headings.

Save using write_analysis with type 'policy_compliance'.""",
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
        cap = self._get_capability("portfolio_readiness") or CAPABILITIES[0]
        return self._execute_capability(cap)

    def _autonomous_job(self):
        """Smart workflow: health check first, action report only if issues detected."""
        if self._paused:
            return
        logger.info("Autonomous scheduled run: starting portfolio readiness check")
        health = self._execute_capability(
            self._get_capability("portfolio_readiness") or CAPABILITIES[0]
        )
        response_text = str(health.get("result", {}).get("response", ""))
        issue_signals = ["breach", "exceed", "anomal", "spike", "critical", "warning",
                         "attention", "above threshold", "below target", "degraded"]
        has_issues = any(s in response_text.lower() for s in issue_signals)
        if has_issues:
            logger.info("Portfolio issues detected -- generating investment action report")
            nba_cap = self._get_capability("investment_action_report")
            if nba_cap:
                self._execute_capability(nba_cap)
        else:
            logger.info("No portfolio issues found -- skipping action report")

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
