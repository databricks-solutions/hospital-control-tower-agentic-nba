import { cn } from '../lib/utils'

function Spinner({ className = '' }) {
  return (
    <svg className={cn("animate-spin h-3 w-3", className)} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

function formatRemaining(autoStopAt) {
  if (!autoStopAt) return null
  const diff = Math.max(0, Math.floor((new Date(autoStopAt + 'Z').getTime() - Date.now()) / 1000))
  if (diff <= 0) return null
  const h = Math.floor(diff / 3600)
  const m = Math.floor((diff % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export default function Header({ mode, setMode, autonomousStatus, onToggleAutonomous, onOpenSettings, healthScore, onCheckHealth, onInjectAnomaly, onInjectGoodData, onResetData, onBackfillData, loadingStates = {}, onOpenGuide, onOpenDocs }) {
  const isRunning = autonomousStatus?.is_running && !autonomousStatus?.is_paused
  const remaining = isRunning ? formatRemaining(autonomousStatus?.auto_stop_at) : null
  
  const getHealthColor = (score) => {
    if (!score) return 'bg-slate-500'
    if (score >= 80) return 'bg-living-green'
    if (score >= 60) return 'bg-amber-500'
    return 'bg-soft-red'
  }

  return (
    <header className="border-b border-slate-700/30 bg-slate-900/80 backdrop-blur-md sticky top-0 z-50">
      <div className="px-6 py-3">
        <div className="flex items-center justify-between">
          {/* Logo & Health */}
          <div className="flex items-center gap-5">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center shadow-lg shadow-teal-500/20">
                <svg className="w-6 h-6 text-slate-900" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                </svg>
              </div>
              <div>
                <h1 className="text-lg font-semibold text-warm-white">Hospital Control Tower</h1>
                <p className="text-xs text-slate-400">Operations Intelligence</p>
              </div>
            </div>
            
            {healthScore && (
              <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-slate-800/50 rounded-lg"
                title="Composite score: 40% LOS + 30% readmission rate + 30% ED breaches">
                <div className={cn("w-2 h-2 rounded-full", getHealthColor(healthScore.score))} />
                <span className="text-sm text-slate-300">
                  Health: <span className="font-medium text-warm-white">{healthScore.score}</span>/100
                </span>
              </div>
            )}
          </div>

          {/* Mode Toggle */}
          <div className="flex items-center gap-1 bg-slate-800/50 rounded-xl p-1">
            <button
              onClick={() => setMode('quick')}
              className={cn(
                "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                mode === 'quick'
                  ? "bg-teal-500 text-slate-900 shadow-lg shadow-teal-500/25"
                  : "text-slate-400 hover:text-warm-white hover:bg-slate-700/50"
              )}
              title="Fast answers (2-5s). Best for specific data lookups, counts, and comparisons."
            >
              Quick Query
            </button>
            <button
              onClick={() => setMode('deep')}
              className={cn(
                "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                mode === 'deep'
                  ? "bg-teal-500 text-slate-900 shadow-lg shadow-teal-500/25"
                  : "text-slate-400 hover:text-warm-white hover:bg-slate-700/50"
              )}
              title="Multi-agent investigation (30-90s). Root cause analysis, reports, and recommendations."
            >
              Deep Analysis
            </button>
          </div>

          {/* Actions & Autonomous Status */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 bg-slate-800/30 rounded-xl px-3 py-1.5 border border-slate-700/30">
              <span className="text-[10px] uppercase tracking-wider text-slate-500 font-medium mr-1">Demo Tools</span>
              <button
                onClick={onCheckHealth}
                disabled={loadingStates.checkHealth}
                className={cn("px-2.5 py-1.5 rounded-lg text-xs font-medium bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 transition-all flex items-center gap-1.5",
                  loadingStates.checkHealth && "opacity-60 cursor-not-allowed")}
                title="Trigger a one-shot health check of all operational metrics"
              >
                {loadingStates.checkHealth && <Spinner />}
                Check Health
              </button>
              <button
                onClick={onInjectGoodData}
                disabled={loadingStates.injectGood}
                className={cn("px-2.5 py-1.5 rounded-lg text-xs font-medium bg-green-500/20 text-green-400 hover:bg-green-500/30 transition-all flex items-center gap-1.5",
                  loadingStates.injectGood && "opacity-60 cursor-not-allowed")}
                title="Add healthy encounters (batch size configurable in Settings)"
              >
                {loadingStates.injectGood && <Spinner />}
                Inject Good
              </button>
              <button
                onClick={onInjectAnomaly}
                disabled={loadingStates.injectAnomaly}
                className={cn("px-2.5 py-1.5 rounded-lg text-xs font-medium bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 transition-all flex items-center gap-1.5",
                  loadingStates.injectAnomaly && "opacity-60 cursor-not-allowed")}
                title="Insert anomalous data across all tables (high LOS, costly drugs, long ED waits)"
              >
                {loadingStates.injectAnomaly && <Spinner />}
                Inject Anomaly
              </button>
              <button
                onClick={onResetData}
                disabled={loadingStates.reset}
                className={cn("px-2.5 py-1.5 rounded-lg text-xs font-medium bg-slate-500/20 text-slate-400 hover:bg-slate-500/30 transition-all flex items-center gap-1.5",
                  loadingStates.reset && "opacity-60 cursor-not-allowed")}
                title="Remove all injected data and clear analysis outputs"
              >
                {loadingStates.reset && <Spinner />}
                Reset
              </button>
              <button
                onClick={onBackfillData}
                disabled={loadingStates.backfill}
                className={cn("px-2.5 py-1.5 rounded-lg text-xs font-medium bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 transition-all flex items-center gap-1.5",
                  loadingStates.backfill && "opacity-60 cursor-not-allowed")}
                title="Generate baseline data for all missing days up to today"
              >
                {loadingStates.backfill && <Spinner />}
                Backfill
              </button>
            </div>

            <div className="flex items-center gap-2 bg-slate-800/50 rounded-xl px-4 py-2">
              <div className={cn(
                "w-2.5 h-2.5 rounded-full transition-all",
                isRunning ? "bg-living-green autonomous-pulse" : "bg-slate-500"
              )} />
              <span className="text-sm text-slate-300">Auto{remaining && <span className="text-slate-500 ml-1">{remaining}</span>}</span>
              <button
                onClick={onToggleAutonomous}
                title={isRunning ? "Stop autonomous monitoring" : "Start autonomous monitoring (auto-stops after 2 hours)"}
                className={cn(
                  "px-2.5 py-1 rounded-lg text-xs font-medium transition-all",
                  isRunning
                    ? "bg-soft-red/20 text-soft-red hover:bg-soft-red/30"
                    : "bg-living-green/20 text-living-green hover:bg-living-green/30"
                )}
              >
                {isRunning ? 'Stop' : 'Start'}
              </button>
            </div>

            <button
              onClick={onOpenGuide}
              className="p-2 text-slate-400 hover:text-warm-white hover:bg-slate-800/50 rounded-lg transition-all"
              title="Open guided demo walkthrough"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
            <button
              onClick={onOpenDocs}
              className="p-2 text-slate-400 hover:text-warm-white hover:bg-slate-800/50 rounded-lg transition-all"
              title="View documentation"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
            </button>
            <button
              onClick={onOpenSettings}
              className="p-2 text-slate-400 hover:text-warm-white hover:bg-slate-800/50 rounded-lg transition-all"
              title="Settings"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}
