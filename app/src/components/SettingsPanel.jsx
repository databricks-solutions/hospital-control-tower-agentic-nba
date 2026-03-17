import { useState, useEffect } from 'react'
import { cn } from '../lib/utils'

const INTERVAL_PRESETS = [
  { label: '1 min', value: 60 },
  { label: '5 min', value: 300 },
  { label: '15 min', value: 900 },
  { label: '1 hour', value: 3600 },
  { label: '1 day', value: 86400 },
]

const DEFAULT_CAPABILITIES = [
  { id: 'concentration_analysis', label: 'Portfolio Concentration Analysis', enabled: true },
  { id: 'performance_monitoring', label: 'Fund Performance Monitoring', enabled: true },
  { id: 'investment_action_report', label: 'Investment Action Report', enabled: true },
  { id: 'flow_analysis', label: 'Fund Flow Analysis', enabled: true },
  { id: 'exposure_analysis', label: 'Exposure Shift Analysis', enabled: true },
  { id: 'policy_compliance', label: 'Investment Policy Compliance', enabled: true },
]

export default function SettingsPanel({ autonomousStatus, onClose, onSave }) {
  const [intervalSec, setIntervalSec] = useState(autonomousStatus?.interval_seconds || 3600)
  const [capabilities, setCapabilities] = useState(DEFAULT_CAPABILITIES)
  const [saving, setSaving] = useState(false)
  const [injectCount, setInjectCount] = useState(() => parseInt(localStorage.getItem('inject_count') || '30', 10))
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    if (autonomousStatus?.interval_seconds) {
      setIntervalSec(autonomousStatus.interval_seconds)
    }
    if (autonomousStatus?.capabilities) {
      setCapabilities(DEFAULT_CAPABILITIES.map(dc => {
        const remote = autonomousStatus.capabilities.find(c => c.id === dc.id)
        return remote ? { ...dc, enabled: remote.enabled } : dc
      }))
    }
  }, [autonomousStatus])

  const handleSave = async () => {
    setSaving(true)
    try {
      localStorage.setItem('inject_count', String(injectCount))
      await fetch('/api/autonomous/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          interval_seconds: intervalSec,
          capabilities: capabilities,
        }),
      })
      onSave?.()
      onClose()
    } catch (err) {
      console.error('Failed to save settings:', err)
    } finally {
      setSaving(false)
    }
  }

  const refreshDates = async () => {
    setRefreshing(true)
    try {
      await fetch('/api/data/refresh-dates', { method: 'POST' })
      onSave?.()
    } catch (err) {
      console.error('Refresh dates failed:', err)
    } finally {
      setRefreshing(false)
    }
  }

  const toggleCapability = (id) => {
    setCapabilities(prev => prev.map(c => 
      c.id === id ? { ...c, enabled: !c.enabled } : c
    ))
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-slate-900/80 backdrop-blur-sm" onClick={onClose} />
      
      <div className="relative w-full max-w-lg bg-slate-800 border border-slate-700/50 rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-700/50 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-warm-white">Autonomous Mode Settings</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-warm-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        
        <div className="px-6 py-5 space-y-6 max-h-[70vh] overflow-y-auto">
          {/* Interval Selection */}
          <div>
            <label className="text-sm text-slate-400 mb-3 block">Run autonomous analysis every:</label>
            <div className="flex flex-wrap gap-2">
              {INTERVAL_PRESETS.map(preset => (
                <button
                  key={preset.value}
                  onClick={() => setIntervalSec(preset.value)}
                  className={cn(
                    "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                    intervalSec === preset.value
                      ? "bg-amber-500 text-slate-900"
                      : "bg-slate-700/50 text-slate-300 hover:bg-slate-700"
                  )}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          {/* Capabilities */}
          <div>
            <label className="text-sm text-slate-400 mb-3 block">Focus areas:</label>
            <div className="space-y-2">
              {capabilities.map(cap => (
                <div 
                  key={cap.id}
                  className={cn(
                    "flex items-center justify-between p-3 rounded-lg transition-all",
                    cap.enabled ? "bg-slate-700/40" : "bg-slate-800/40 opacity-60"
                  )}
                >
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => toggleCapability(cap.id)}
                      className={cn(
                        "w-5 h-5 rounded border-2 flex items-center justify-center transition-all",
                        cap.enabled 
                          ? "bg-amber-500 border-amber-500" 
                          : "border-slate-500"
                      )}
                    >
                      {cap.enabled && (
                        <svg className="w-3 h-3 text-slate-900" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                    </button>
                    <span className={cn(
                      "text-sm",
                      cap.enabled ? "text-warm-white" : "text-slate-500"
                    )}>
                      {cap.label}
                    </span>
                  </div>
                  <span className="text-xs text-slate-500">{cap.enabled ? 'On' : 'Off'}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Demo Data */}
          <div className="border-t border-slate-700/50 pt-5">
            <label className="text-sm text-slate-400 mb-3 block">Demo Data</label>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-300">Injection batch size</span>
                <div className="flex items-center gap-2">
                  <input
                    type="range" min="1" max="1000" value={injectCount}
                    onChange={e => setInjectCount(parseInt(e.target.value, 10))}
                    className="w-32 accent-amber-500"
                  />
                  <input
                    type="number" min="1" max="1000" value={injectCount}
                    onChange={e => setInjectCount(Math.max(1, Math.min(1000, parseInt(e.target.value, 10) || 1)))}
                    className="w-16 bg-slate-700/50 border border-slate-600/50 rounded-lg px-2 py-1 text-sm text-warm-white text-center"
                  />
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-sm text-slate-300">Refresh data dates</span>
                  <p className="text-xs text-slate-500 mt-0.5">Shift base data forward if older than 3 days</p>
                </div>
                <button
                  onClick={refreshDates}
                  disabled={refreshing}
                  className="px-3 py-1.5 bg-slate-700/50 text-slate-300 rounded-lg text-xs font-medium hover:bg-slate-700 transition-all disabled:opacity-50"
                >
                  {refreshing ? 'Refreshing...' : 'Refresh Now'}
                </button>
              </div>
            </div>
          </div>
        </div>
        
        <div className="px-6 py-4 border-t border-slate-700/50 flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-warm-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2 bg-amber-500 text-slate-900 rounded-lg font-medium 
                     hover:bg-amber-400 transition-all disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

