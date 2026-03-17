import { useState, useEffect, useCallback, useRef } from 'react'
import Header from './components/Header'
import ConversationView from './components/ConversationView'
import DashboardPanel from './components/DashboardPanel'
import SettingsPanel from './components/SettingsPanel'
import DemoGuide from './components/DemoGuide'
import DocsViewer from './components/DocsViewer'

function Toast({ toast, onDismiss }) {
  const colors = {
    success: 'bg-green-600/90 border-green-500/50',
    error: 'bg-red-600/90 border-red-500/50',
    info: 'bg-blue-600/90 border-blue-500/50',
  }
  return (
    <div className={`${colors[toast.type] || colors.info} border text-white text-sm px-4 py-3 rounded-lg shadow-lg backdrop-blur-sm flex items-center gap-3 toast-enter`}>
      <span className="flex-1">{toast.message}</span>
      <button onClick={() => onDismiss(toast.id)} className="text-white/60 hover:text-white text-xs">x</button>
    </div>
  )
}

function App() {
  const [mode, setMode] = useState('quick')
  const [autonomousStatus, setAutonomousStatus] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [healthScore, setHealthScore] = useState(null)
  const [pendingQuery, setPendingQuery] = useState(null)
  const [toasts, setToasts] = useState([])
  const [loadingStates, setLoadingStates] = useState({})
  const [showGuide, setShowGuide] = useState(() => !localStorage.getItem('demo_guide_seen'))
  const [showDocs, setShowDocs] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const toastIdRef = useRef(0)

  const addToast = useCallback((message, type = 'success') => {
    const id = ++toastIdRef.current
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3000)
  }, [])

  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const setLoading = (key, val) => setLoadingStates(prev => ({ ...prev, [key]: val }))

  const dismissGuide = () => {
    setShowGuide(false)
    localStorage.setItem('demo_guide_seen', '1')
  }

  const fetchAutonomousStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/autonomous/status')
      if (res.ok) setAutonomousStatus(await res.json())
    } catch (err) {
      console.error('Failed to fetch autonomous status:', err)
    }
  }, [])

  const fetchHealthScore = useCallback(async () => {
    try {
      const res = await fetch('/api/health/score')
      if (res.ok) setHealthScore(await res.json())
    } catch (err) { /* Health endpoint may not exist yet */ }
  }, [])

  useEffect(() => {
    fetchAutonomousStatus()
    fetchHealthScore()
    fetch('/api/config').catch(() => {})
    const interval = setInterval(() => {
      fetchAutonomousStatus()
      fetchHealthScore()
    }, 30000)
    return () => clearInterval(interval)
  }, [fetchAutonomousStatus, fetchHealthScore])

  const toggleAutonomous = async () => {
    const endpoint = autonomousStatus?.is_running
      ? '/api/autonomous/stop'
      : '/api/autonomous/start'
    try {
      await fetch(endpoint, { method: 'POST' })
      fetchAutonomousStatus()
    } catch (err) {
      console.error('Autonomous toggle failed:', err)
    }
  }

  const checkHealthNow = async () => {
    setLoading('checkHealth', true)
    try {
      await fetch('/api/autonomous/check-now', { method: 'POST' })
      addToast('Health check triggered')
      setTimeout(fetchHealthScore, 3000)
    } catch (err) {
      addToast('Health check failed', 'error')
    } finally {
      setLoading('checkHealth', false)
    }
  }

  const getInjectCount = () => parseInt(localStorage.getItem('inject_count') || '30', 10)

  const injectAnomaly = async () => {
    setLoading('injectAnomaly', true)
    const count = getInjectCount()
    try {
      const res = await fetch('/api/data/inject-anomaly', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && !data.error) {
        addToast(`Injected ${data.encounters || count} underperforming positions + flow/exposure data`)
        setTimeout(() => { fetchHealthScore(); setRefreshKey(k => k + 1) }, 2000)
      } else {
        addToast(`Inject risk failed: ${data.error || res.statusText}`, 'error')
      }
    } catch (err) {
      addToast(`Inject risk failed: ${err.message}`, 'error')
    } finally {
      setLoading('injectAnomaly', false)
    }
  }

  const injectGoodData = async () => {
    setLoading('injectGood', true)
    const count = getInjectCount()
    try {
      const res = await fetch('/api/data/inject-good', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && !data.error) {
        addToast(`Injected ${data.encounters || count} healthy returns + flow/exposure data`)
        setTimeout(() => { fetchHealthScore(); setRefreshKey(k => k + 1) }, 2000)
      } else {
        addToast(`Inject returns failed: ${data.error || res.statusText}`, 'error')
      }
    } catch (err) {
      addToast(`Inject returns failed: ${err.message}`, 'error')
    } finally {
      setLoading('injectGood', false)
    }
  }

  const resetDemoData = async () => {
    setLoading('reset', true)
    try {
      const res = await fetch('/api/data/reset', { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (res.ok && !data.error) {
        addToast('Demo data reset -- injected data and analyses cleared')
        setTimeout(() => { fetchHealthScore(); setRefreshKey(k => k + 1) }, 2000)
      } else {
        addToast(`Reset failed: ${data.error || res.statusText}`, 'error')
      }
    } catch (err) {
      addToast(`Reset failed: ${err.message}`, 'error')
    } finally {
      setLoading('reset', false)
    }
  }

  const backfillData = async () => {
    setLoading('backfill', true)
    try {
      const res = await fetch('/api/data/backfill', { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (res.ok && !data.error) {
        addToast(`Backfilled ${data.days_filled} days (${data.encounters} encounters)`)
        setTimeout(() => { fetchHealthScore(); setRefreshKey(k => k + 1) }, 2000)
      } else {
        addToast(`Backfill failed: ${data.error || res.statusText}`, 'error')
      }
    } catch (err) {
      addToast(`Backfill failed: ${err.message}`, 'error')
    } finally {
      setLoading('backfill', false)
    }
  }

  // Poll autonomous latest result for toast notifications
  const lastAutoTs = useRef(null)
  useEffect(() => {
    const pollAuto = async () => {
      try {
        const res = await fetch('/api/autonomous/latest-result')
        if (res.ok) {
          const data = await res.json()
          if (data.timestamp && data.timestamp !== lastAutoTs.current) {
            lastAutoTs.current = data.timestamp
            const msg = data.issues_found ? 'Health check: issues detected' : 'Health check: no issues found'
            addToast(msg, data.issues_found ? 'error' : 'info')
            fetchHealthScore()
            setRefreshKey(k => k + 1)
          }
        }
      } catch {}
    }
    const iv = setInterval(pollAuto, 15000)
    return () => clearInterval(iv)
  }, [addToast, fetchHealthScore])

  return (
    <div className="h-screen flex flex-col bg-gradient-main text-warm-white overflow-hidden">
      <div className="bg-amber-500/90 text-slate-900 text-center text-xs py-1 font-medium flex-shrink-0">
        Demo Environment &mdash; Synthetic data for illustration purposes only
      </div>
      <Header
        mode={mode}
        setMode={setMode}
        autonomousStatus={autonomousStatus}
        onToggleAutonomous={toggleAutonomous}
        onOpenSettings={() => setShowSettings(true)}
        healthScore={healthScore}
        onCheckHealth={checkHealthNow}
        onInjectAnomaly={injectAnomaly}
        onInjectGoodData={injectGoodData}
        onResetData={resetDemoData}
        onBackfillData={backfillData}
        loadingStates={loadingStates}
        onOpenGuide={() => setShowGuide(true)}
        onOpenDocs={() => setShowDocs(true)}
      />

      <main className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-hidden">
          <ConversationView
            mode={mode}
            healthScore={healthScore}
            onRefresh={fetchHealthScore}
            pendingQuery={pendingQuery}
            onPendingQueryHandled={() => setPendingQuery(null)}
          />
        </div>
        <DashboardPanel onQuerySelect={(q) => setPendingQuery(q)} refreshKey={refreshKey} />
      </main>

      {showSettings && (
        <SettingsPanel
          autonomousStatus={autonomousStatus}
          onClose={() => setShowSettings(false)}
          onSave={fetchAutonomousStatus}
        />
      )}

      {showGuide && <DemoGuide onClose={dismissGuide} />}
      {showDocs && <DocsViewer onClose={() => setShowDocs(false)} />}

      {toasts.length > 0 && (
        <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
          {toasts.map(t => <Toast key={t.id} toast={t} onDismiss={dismissToast} />)}
        </div>
      )}
    </div>
  )
}

export default App
