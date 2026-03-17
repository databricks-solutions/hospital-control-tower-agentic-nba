"""Agent module for Investment Intelligence Platform."""
from .graph import invoke_agent, get_llm
from .autonomous import (
    get_autonomous,
    start_autonomous,
    stop_autonomous,
    CAPABILITIES,
    AutonomousScheduler
)
from .tools import (
    execute_sql,
    search_fund_documents,
    analyze_performance_drivers,
    analyze_concentration,
    check_fund_flows,
    check_exposure_shifts,
    check_portfolio_kpis,
    write_analysis,
    ALL_TOOLS,
    QUICK_TOOLS,
    DEEP_TOOLS,
)

__all__ = [
    "invoke_agent",
    "get_llm",
    "get_autonomous",
    "start_autonomous",
    "stop_autonomous",
    "CAPABILITIES",
    "AutonomousScheduler",
    "execute_sql",
    "search_fund_documents",
    "analyze_performance_drivers",
    "analyze_concentration",
    "check_fund_flows",
    "check_exposure_shifts",
    "check_portfolio_kpis",
    "write_analysis",
    "ALL_TOOLS",
    "QUICK_TOOLS",
    "DEEP_TOOLS",
]
