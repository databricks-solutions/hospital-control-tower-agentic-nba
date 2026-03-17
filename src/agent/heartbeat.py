"""Heartbeat scheduler for autonomous agent actions."""
import os
import logging
import random
from datetime import datetime
from typing import Callable, List, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .graph import invoke_agent

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "60"))


class HeartbeatCapability:
    """Defines an autonomous capability the agent can perform."""
    
    def __init__(self, name: str, prompt: str, analysis_type: str):
        self.name = name
        self.prompt = prompt
        self.analysis_type = analysis_type


CAPABILITIES = [
    HeartbeatCapability(
        name="performance_drivers",
        prompt="""Monitor fund performance across portfolios for anomalies and drivers.

1. Query fact_fund_performance for the last 30 days grouped by fund_name and holding_category
2. Compare current month returns to prior months - flag any >30% swings
3. Identify the top 10 highest-return holdings and check for concentration risk
4. Check fact_portfolio_kpis for return_per_holding trends by fund

Provide insights on performance drivers and policy-grounded recommendations.
Save your analysis using write_analysis with type 'performance_drivers'.""",
        analysis_type="performance_drivers",
    ),
    HeartbeatCapability(
        name="concentration",
        prompt="""Analyze portfolio concentration patterns and diversification opportunities.

1. Query dim_funds for holding period by fund_name, sector, and rebalance day of week
2. Identify sectors with avg holding period > 5.0 quarters
3. Analyze rebalance day effect - compare Monday rebalances to other days
4. Check rebalance rates for correlation with short holding periods
5. Compare Fund_A concentration to Fund_B and Fund_C

Recommend specific actions to improve diversification with policy citations.
Save your analysis using write_analysis with type 'concentration'.""",
        analysis_type="concentration",
    ),
    HeartbeatCapability(
        name="exposure_shifts",
        prompt="""Analyze portfolio exposure patterns and allocation efficiency.

1. Query fact_portfolio_holdings for exposure percentage by sector
2. Identify sectors where partial positions > 25% of total holdings
3. Calculate allocation differential: full vs partial positions per sector
4. Check trends - is exposure concentration increasing?

Recommend optimal allocation strategies.
Save your analysis using write_analysis with type 'exposure_shifts'.""",
        analysis_type="exposure_shifts",
    ),
]


class HeartbeatScheduler:
    """Manages periodic autonomous agent actions."""
    
    def __init__(self, interval_seconds: int = HEARTBEAT_INTERVAL):
        self.interval = interval_seconds
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        self.last_execution: Optional[datetime] = None
        self.last_capability: Optional[str] = None
        self.execution_count = 0
        self._paused = False
        self._callbacks: List[Callable] = []
    
    def add_callback(self, callback: Callable):
        self._callbacks.append(callback)
    
    def _execute_capability(self, capability: HeartbeatCapability):
        logger.info(f"Heartbeat executing: {capability.name}")
        try:
            result = invoke_agent(message=capability.prompt, mode="rag")
            self.last_execution = datetime.utcnow()
            self.last_capability = capability.name
            self.execution_count += 1
            logger.info(f"Heartbeat completed: {capability.name}")
            for callback in self._callbacks:
                try:
                    callback({
                        "capability": capability.name,
                        "timestamp": self.last_execution.isoformat(),
                        "success": True,
                        "tools_used": result.get("tool_calls", []),
                    })
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            return result
        except Exception as e:
            logger.error(f"Heartbeat error in {capability.name}: {e}")
            return {"error": str(e)}
    
    def _heartbeat_job(self):
        if self._paused:
            return
        capability_index = self.execution_count % len(CAPABILITIES)
        capability = CAPABILITIES[capability_index]
        self._execute_capability(capability)
    
    def start(self):
        if self.is_running:
            return
        self.scheduler.add_job(self._heartbeat_job, trigger=IntervalTrigger(seconds=self.interval),
                               id="heartbeat_job", replace_existing=True)
        self.scheduler.start()
        self.is_running = True
        logger.info(f"Heartbeat started with {self.interval}s interval")
    
    def stop(self):
        if not self.is_running:
            return
        self.scheduler.shutdown(wait=False)
        self.is_running = False
        logger.info("Heartbeat stopped")
    
    def pause(self):
        self._paused = True
    
    def resume(self):
        self._paused = False
    
    def trigger_now(self, capability_name: Optional[str] = None):
        if capability_name:
            for cap in CAPABILITIES:
                if cap.name == capability_name:
                    return self._execute_capability(cap)
            raise ValueError(f"Unknown capability: {capability_name}")
        return self._heartbeat_job()
    
    def get_status(self) -> dict:
        return {
            "is_running": self.is_running, "is_paused": self._paused,
            "interval_seconds": self.interval,
            "last_execution": self.last_execution.isoformat() if self.last_execution else None,
            "last_capability": self.last_capability, "execution_count": self.execution_count,
            "capabilities": [c.name for c in CAPABILITIES],
        }


_heartbeat: Optional[HeartbeatScheduler] = None


def get_heartbeat() -> HeartbeatScheduler:
    global _heartbeat
    if _heartbeat is None:
        _heartbeat = HeartbeatScheduler()
    return _heartbeat


def start_heartbeat():
    get_heartbeat().start()


def stop_heartbeat():
    if _heartbeat:
        _heartbeat.stop()
