import { useState, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { cn } from '../lib/utils'
import ChartRenderer from './ChartRenderer'

function StatCard({ title, value, subtitle, trend, color = 'teal', tooltip }) {
  const colorClasses = {
    teal: 'from-teal-500/20 to-teal-600/10 border-teal-500/30',
    red: 'from-red-500/20 to-red-600/10 border-red-500/30',
    green: 'from-green-500/20 to-green-600/10 border-green-500/30',
    blue: 'from-blue-500/20 to-blue-600/10 border-blue-500/30',
  }
  return (
    <div className={cn("p-4 rounded-xl bg-gradient-to-br border", colorClasses[color])} title={tooltip}>
      <p className="text-xs text-slate-400 uppercase tracking-wide mb-1">{title}</p>
      <p className="text-2xl font-semibold text-warm-white">{value}</p>
      {subtitle && <p className="text-xs text-slate-400 mt-1">{subtitle}</p>}
      {trend !== undefined && trend !== null && (
        <p className={cn("text-xs mt-1", trend > 0 ? "text-green-400" : "text-red-400")}>
          {trend > 0 ? '\u2191' : '\u2193'} {Math.abs(trend)}% vs last period
        </p>
      )}
    </div>
  )
}

function FundPerformanceTile({ data }) {
  if (!data || !data.series?.length) {
    return (
      <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
        <h4 className="text-xs font-medium text-slate-400 uppercase mb-2">Fund Performance</h4>
        <p className="text-xs text-slate-500">No fund performance data yet. Run the generate_data job or click "Inject Good" to add sample data.</p>
      </div>
    )
  }
  const spec = {
    type: 'line',
    title: null,
    data: data.series,
    xKey: data.xKey || 'period',
    yKeys: data.yKeys || data.strategies || ['return'],
  }
  return (
    <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
      <h4 className="text-xs font-medium text-slate-400 uppercase mb-3" title="Monthly returns by strategy">Fund Performance</h4>
      <ChartRenderer spec={spec} />
    </div>
  )
}

function CapitalFlowsTile({ data }) {
  if (!data || !data.strategies?.length) {
    return (
      <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
        <h4 className="text-xs font-medium text-slate-400 uppercase mb-2">Capital Flows</h4>
        <p className="text-xs text-slate-500">No capital flow data yet. Use Inject Good to add sample data.</p>
      </div>
    )
  }
  const chartData = data.strategies.map(s => ({
    strategy: s.strategy,
    capital_calls: s.capital_calls ?? 0,
    distributions: s.distributions ?? 0,
  }))
  const spec = {
    type: 'bar',
    title: null,
    data: chartData,
    xKey: 'strategy',
    yKeys: ['capital_calls', 'distributions'],
  }
  return (
    <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
      <h4 className="text-xs font-medium text-slate-400 uppercase mb-3" title="Capital calls vs distributions by strategy">Capital Flows</h4>
      <ChartRenderer spec={spec} />
    </div>
  )
}

function WatchlistFundItem({ fund }) {
  const returnLow = parseFloat(fund.return_pct) < 0
  const aumHigh = (fund.aum || 0) > 1000
  return (
    <div className="py-2.5 border-b border-slate-700/30 last:border-0">
      <div className="flex items-center justify-between mb-1">
        <p className="text-sm text-warm-white font-medium">{fund.fund_name || fund.fund_id}</p>
        <span className={cn("text-xs px-2 py-0.5 rounded",
          returnLow ? "bg-red-500/20 text-red-400" : "bg-slate-500/20 text-slate-400")}>
          Return: {fund.return_pct ?? 'N/A'}%
        </span>
      </div>
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>{fund.manager || fund.strategy || 'N/A'}</span>
        {(fund.aum || 0) > 0 && (
          <span className={cn(aumHigh ? "text-amber-400" : "text-slate-400")}>
            ${fund.aum >= 1000 ? `${(fund.aum / 1000).toFixed(1)}B` : `${fund.aum.toFixed(0)}M`} AUM
          </span>
        )}
      </div>
      {fund.strategy && (
        <p className="text-[10px] text-slate-500 mt-0.5">{fund.strategy} — flagged {fund.flagged_date || 'N/A'}</p>
      )}
    </div>
  )
}

const TYPE_LABELS = {
  cost_monitoring: 'Cost Alert',
  los_analysis: 'Performance Analysis',
  ed_performance: 'Flow Alert',
  staffing_analysis: 'Allocation Optimization',
  compliance_monitoring: 'Compliance Check',
  next_best_action_report: 'Recommended Actions',
  readiness_check: 'Readiness Check',
  performance_alert: 'Performance Alert',
  concentration_risk: 'Concentration Risk',
  rebalance_suggestion: 'Rebalance Suggestion',
}

function RecommendationItem({ rec }) {
  const typeColors = {
    cost_monitoring: 'bg-red-500/20 text-red-400',
    los_analysis: 'bg-blue-500/20 text-blue-400',
    ed_performance: 'bg-amber-500/20 text-amber-400',
    staffing_analysis: 'bg-green-500/20 text-green-400',
    compliance_monitoring: 'bg-purple-500/20 text-purple-400',
    next_best_action_report: 'bg-teal-500/20 text-teal-400',
    readiness_check: 'bg-slate-500/20 text-slate-400',
    performance_alert: 'bg-red-500/20 text-red-400',
    concentration_risk: 'bg-amber-500/20 text-amber-400',
    rebalance_suggestion: 'bg-green-500/20 text-green-400',
  }
  const label = TYPE_LABELS[rec.type] || rec.type?.replace(/_/g, ' ')
  return (
    <div className="py-3 border-b border-slate-700/30 last:border-0">
      <div className="flex items-center justify-between mb-1">
        <span className={cn("text-[10px] px-2 py-0.5 rounded",
          typeColors[rec.type] || 'bg-slate-500/20 text-slate-400')}>
          {label}
        </span>
        {rec.timestamp && (
          <span className="text-[10px] text-slate-500">
            {new Date(rec.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>
      <div className="prose prose-invert prose-xs max-w-none prose-p:text-warm-white prose-strong:text-teal-400 prose-ul:text-warm-white prose-li:text-warm-white prose-p:my-1 prose-ul:my-1 prose-li:my-0.5">
        <ReactMarkdown>{rec.action}</ReactMarkdown>
      </div>
    </div>
  )
}

function AlertTile({ alert, onClick }) {
  const severityColors = {
    high: 'border-red-500/40 bg-red-500/10 hover:bg-red-500/20',
    medium: 'border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/20',
    low: 'border-blue-500/40 bg-blue-500/10 hover:bg-blue-500/20',
  }
  return (
    <button onClick={onClick}
      title="Click to investigate this alert with the AI agent"
      className={cn("w-full text-left p-3 rounded-lg border transition-all",
        severityColors[alert.severity] || severityColors.medium)}>
      <p className="text-xs font-medium text-warm-white">{alert.title}</p>
      <p className="text-[10px] text-slate-400 mt-0.5">{alert.detail}</p>
    </button>
  )
}

function CollapsibleSection({ title, count, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-slate-800/30 rounded-xl border border-slate-700/30">
      <button onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-3 text-left hover:bg-slate-700/10 transition-colors rounded-xl">
        <h4 className="text-xs font-medium text-slate-400 uppercase">{title}</h4>
        <div className="flex items-center gap-2">
          {count > 0 && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-teal-500/20 text-teal-400">{count}</span>}
          <span className={cn("text-slate-500 text-xs transition-transform", open && "rotate-180")}>&#9662;</span>
        </div>
      </button>
      {open && <div className="px-4 pb-3">{children}</div>}
    </div>
  )
}

function EmptyTile({ title, message }) {
  return (
    <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
      <h4 className="text-xs font-medium text-slate-400 uppercase mb-2">{title}</h4>
      <p className="text-xs text-slate-500">{message}</p>
    </div>
  )
}

function AUMTrendTile({ data }) {
  if (!data || !data.series?.length) return <EmptyTile title="AUM Trend" message="No AUM trend data yet. Use Inject Good to add sample data." />
  const spec = {
    type: 'line',
    title: null,
    data: data.series,
    xKey: data.xKey || 'period',
    yKeys: data.yKeys || ['aum'],
  }
  return (
    <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
      <h4 className="text-xs font-medium text-slate-400 uppercase mb-3" title="Assets under management over time">AUM Trend</h4>
      <ChartRenderer spec={spec} />
    </div>
  )
}

function SectorExposureTile({ data }) {
  if (!data || !data.sectors?.length) return <EmptyTile title="Sector Exposure" message="No sector exposure data yet. Use Inject Good to add sample data." />
  const chartData = data.sectors.map(s => ({
    name: s.sector,
    value: s.pct ?? s.value ?? 0,
  }))
  const spec = {
    type: 'pie',
    title: null,
    data: chartData,
    xKey: 'name',
    yKeys: ['value'],
  }
  return (
    <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
      <h4 className="text-xs font-medium text-slate-400 uppercase mb-3" title="Portfolio allocation by sector">Sector Exposure</h4>
      <ChartRenderer spec={spec} />
    </div>
  )
}

function ReturnsByStrategyTile({ data }) {
  if (!data || !data.strategies?.length) return <EmptyTile title="Returns by Strategy" message="No return data available." />
  const chartData = data.strategies.map(s => ({
    strategy: s.strategy,
    return: s.avg_return ?? s.return ?? 0,
  }))
  const spec = {
    type: 'bar',
    title: null,
    data: chartData,
    xKey: 'strategy',
    yKeys: ['return'],
  }
  return (
    <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
      <h4 className="text-xs font-medium text-slate-400 uppercase mb-3" title="Average return by strategy">Returns by Strategy</h4>
      <ChartRenderer spec={spec} />
    </div>
  )
}

function StrategyAllocationTile({ data }) {
  if (!data || !data.strategies?.length) return <EmptyTile title="Strategy Allocation" message="No allocation data available." />
  const chartData = data.strategies.map(s => ({
    name: s.strategy,
    value: s.count ?? s.pct ?? s.value ?? 0,
  }))
  const spec = {
    type: 'pie',
    title: null,
    data: chartData,
    xKey: 'name',
    yKeys: ['value'],
  }
  return (
    <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
      <h4 className="text-xs font-medium text-slate-400 uppercase mb-3" title="Portfolio allocation by strategy">Strategy Allocation</h4>
      <ChartRenderer spec={spec} />
    </div>
  )
}

function PortfolioHealthTrendTile({ data }) {
  if (!data || data.length < 2) return null
  const scores = data.map(d => d.score).filter(Boolean)
  if (scores.length < 2) return null
  const max = Math.max(...scores, 100)
  const min = Math.min(...scores, 0)
  const range = max - min || 1
  return (
    <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
      <h4 className="text-xs font-medium text-slate-400 uppercase mb-3" title="Portfolio health score trend over recent checks">Portfolio Health Trend</h4>
      <div className="flex items-end gap-1 h-12">
        {data.slice(-15).map((d, i) => (
          <div key={i} className="flex-1 flex flex-col justify-end">
            <div className={cn("rounded-t", d.score >= 80 ? "bg-green-500/60" : d.score >= 60 ? "bg-amber-500/60" : "bg-red-500/60")}
              style={{ height: `${Math.max(4, ((d.score - min) / range) * 40)}px` }}
              title={`${d.score}/100`} />
          </div>
        ))}
      </div>
    </div>
  )
}

export default function DashboardPanel({ onQuerySelect, refreshKey }) {
  const [summary, setSummary] = useState(null)
  const [fundPerformance, setFundPerformance] = useState(null)
  const [watchlist, setWatchlist] = useState([])
  const [recommendations, setRecommendations] = useState([])
  const [alerts, setAlerts] = useState([])
  const [capitalFlows, setCapitalFlows] = useState(null)
  const [aumTrend, setAumTrend] = useState(null)
  const [sectorExposure, setSectorExposure] = useState(null)
  const [returnsByStrategy, setReturnsByStrategy] = useState([])
  const [strategyAllocation, setStrategyAllocation] = useState([])
  const [healthHistory, setHealthHistory] = useState([])
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const [summaryRes, perfRes, watchlistRes, recsRes, alertsRes, flowsRes, aumRes, sectorRes, returnsRes, allocRes, histRes] = await Promise.all([
        fetch('/api/dashboard/summary'),
        fetch('/api/dashboard/fund-performance?months=12'),
        fetch('/api/dashboard/watchlist?limit=5'),
        fetch('/api/recommendations/latest?limit=3'),
        fetch('/api/alerts/active'),
        fetch('/api/dashboard/capital-flows'),
        fetch('/api/dashboard/aum-trend'),
        fetch('/api/dashboard/sector-exposure'),
        fetch('/api/dashboard/returns-by-strategy'),
        fetch('/api/dashboard/strategy-allocation'),
        fetch('/api/dashboard/health-history'),
      ])
      const [summaryData, perfData, watchlistData, recsData, alertsData, flowsD, aumD, sectorD, returnsD, allocD, histD] = await Promise.all([
        summaryRes.json(), perfRes.json(), watchlistRes.json(), recsRes.json(), alertsRes.json(),
        flowsRes.json(), aumRes.json(), sectorRes.json(), returnsRes.json(), allocRes.json(), histRes.json(),
      ])
      setSummary(summaryData.summary ?? summaryData)
      setFundPerformance(perfData.fund_performance ?? perfData)
      setWatchlist(watchlistData.funds ?? watchlistData.watchlist ?? [])
      setRecommendations(recsData.recommendations ?? [])
      setAlerts(alertsData.alerts ?? [])
      setCapitalFlows(flowsD.capital_flows ?? flowsD)
      setAumTrend(aumD.aum_trend ?? aumD)
      setSectorExposure(sectorD.sector_exposure ?? sectorD)
      setReturnsByStrategy(returnsD.strategies ?? returnsD ?? [])
      setStrategyAllocation(allocD.strategies ?? allocD ?? [])
      setHealthHistory(histD.history ?? histD ?? [])
    } catch (err) {
      console.error('Dashboard fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 60000)
    return () => clearInterval(interval)
  }, [fetchData, refreshKey])

  if (loading) {
    return (
      <div className="w-[480px] flex-shrink-0 bg-slate-900/30 border-l border-slate-700/30 p-4">
        <div className="animate-pulse space-y-4">
          <div className="h-20 bg-slate-800/50 rounded-xl" />
          <div className="h-20 bg-slate-800/50 rounded-xl" />
          <div className="h-32 bg-slate-800/50 rounded-xl" />
        </div>
      </div>
    )
  }

  return (
    <div className="w-[480px] flex-shrink-0 bg-slate-900/30 border-l border-slate-700/30 overflow-y-auto custom-scrollbar">
      <div className="p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-warm-white">Portfolio Intelligence</h3>
          <button onClick={fetchData} className="text-xs text-slate-400 hover:text-white transition-colors">Refresh</button>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <StatCard title="Total AUM"
            value={summary?.total_aum != null ? (summary.total_aum >= 1000 ? `$${(summary.total_aum / 1000).toFixed(1)}B` : `$${summary.total_aum.toFixed(0)}M`) : '—'}
            trend={summary?.trends?.aum_trend}
            tooltip="Total assets under management"
            color="blue" />
          <StatCard title="Avg Return"
            value={summary?.avg_return != null ? `${summary.avg_return}%` : (summary?.avg_return ?? '—')}
            trend={summary?.trends?.return_trend}
            tooltip="Average portfolio return. Benchmark-relative performance"
            color={parseFloat(summary?.avg_return) < 0 ? 'red' : parseFloat(summary?.avg_return) > 5 ? 'green' : 'teal'} />
          <StatCard title="Concentration %"
            value={summary?.concentration_pct != null ? `${summary.concentration_pct}%` : (summary?.concentration_pct ?? '—')}
            trend={summary?.trends?.concentration_trend}
            tooltip="Largest single position as % of portfolio. Target: under 25%"
            color={parseFloat(summary?.concentration_pct) > 25 ? 'red' : 'green'} />
          <StatCard title="Watchlist"
            value={summary?.watchlist_count ?? watchlist.length ?? 0}
            subtitle={`${watchlist.length} funds flagged`}
            trend={summary?.trends?.watchlist_trend}
            tooltip="Funds underperforming or requiring review"
            color={(summary?.watchlist_count ?? watchlist.length) > 0 ? 'red' : 'green'} />
        </div>

        <FundPerformanceTile data={fundPerformance} />

        <PortfolioHealthTrendTile data={healthHistory} />

        {alerts.length > 0 && (
          <CollapsibleSection title="Active Alerts" count={alerts.length}>
            <div className="space-y-2">
              {alerts.map((a, i) => (
                <AlertTile key={i} alert={a} onClick={() => onQuerySelect?.(
                  `Investigate the ${a.title.toLowerCase()} issue: ${a.detail}`
                )} />
              ))}
            </div>
          </CollapsibleSection>
        )}

        <div className="grid grid-cols-2 gap-3">
          <ReturnsByStrategyTile data={{ strategies: returnsByStrategy }} />
          <StrategyAllocationTile data={{ strategies: strategyAllocation }} />
        </div>

        <CapitalFlowsTile data={capitalFlows} />
        <AUMTrendTile data={aumTrend} />
        <SectorExposureTile data={sectorExposure} />

        <div className="bg-slate-800/30 rounded-xl p-4 border border-slate-700/30">
          <h4 className="text-xs font-medium text-slate-400 uppercase mb-2" title="Underperforming funds flagged for review, sorted by most recent">Watchlist Funds</h4>
          {watchlist.length > 0 ? (
            watchlist.map((fund, i) => <WatchlistFundItem key={i} fund={fund} />)
          ) : (
            <p className="text-xs text-slate-500 py-2">No watchlist funds. Use "Inject Anomaly" to generate test underperforming fund data.</p>
          )}
        </div>

        <CollapsibleSection title="Recommended Actions" count={recommendations.length}>
          {recommendations.length > 0 ? (
            recommendations.map((rec, i) => <RecommendationItem key={i} rec={rec} />)
          ) : (
            <p className="text-xs text-slate-500 py-2">No recommendations yet. Start Autonomous mode or run a Deep Analysis to generate action items.</p>
          )}
        </CollapsibleSection>
      </div>
    </div>
  )
}
