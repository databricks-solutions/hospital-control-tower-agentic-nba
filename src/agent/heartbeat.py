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
        name="cost_monitoring",
        prompt="""Monitor drug costs across hospitals for anomalies and spikes.

1. Query fact_drug_costs for the last 30 days grouped by hospital and drug_category
2. Compare current month spend to prior months - flag any >30% increases
3. Identify the top 10 highest-cost drugs and check for unit cost outliers
4. Check fact_operational_kpis for drug_cost_per_encounter trends by hospital

Provide insights on cost anomalies and SOP-grounded recommendations.
Save your analysis using write_analysis with type 'cost_monitoring'.""",
        analysis_type="cost_monitoring",
    ),
    HeartbeatCapability(
        name="los_analysis",
        prompt="""Analyze length of stay patterns and identify reduction opportunities.

1. Query dim_encounters for LOS by hospital, department, and discharge day of week
2. Identify departments with avg LOS > 5.0 days
3. Analyze Monday discharge effect - compare Monday LOS to other days
4. Check readmission rates for correlation with short LOS (premature discharge)
5. Compare Hospital_A LOS to Hospital_B and Hospital_C

Recommend specific actions to reduce LOS with SOP citations.
Save your analysis using write_analysis with type 'los_analysis'.""",
        analysis_type="los_analysis",
    ),
    HeartbeatCapability(
        name="staffing_optimization",
        prompt="""Analyze staffing patterns and contract labor efficiency.

1. Query fact_staffing for contract labor percentage by department
2. Identify departments where contract labor > 25% of total FTEs
3. Calculate cost differential: contract vs full-time per department
4. Check trends - is contract labor increasing?

Recommend optimal staffing strategies.
Save your analysis using write_analysis with type 'staffing_analysis'.""",
        analysis_type="staffing_analysis",
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
