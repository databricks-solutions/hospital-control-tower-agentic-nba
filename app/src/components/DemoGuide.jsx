import { useState } from 'react'

const STEPS = [
  {
    title: 'Welcome to Investment Intelligence Platform',
    body: 'An AI-powered portfolio companion for investment operations. It monitors portfolio health, answers questions about your data, and recommends actions grounded in your investment policies.',
  },
  {
    title: 'Dashboard',
    body: 'The right panel shows real-time portfolio metrics: fund flows, concentration, returns, exposure shifts, and compliance status. Trend arrows show week-over-week changes.',
  },
  {
    title: 'Ask a Question',
    body: 'Use Quick Query for fast data lookups (2-5s), or Deep Analysis for multi-agent root-cause investigations (30-90s). Click a suggestion chip to get started.',
  },
  {
    title: 'Demo Tools',
    body: '"Inject Returns" adds healthy returns data, "Inject Risk" adds underperforming positions, and "Check Health" triggers an immediate portfolio health check. Use these to show how the system responds to changing data.',
  },
  {
    title: 'Autonomous Mode',
    body: 'Click "Auto Start" to enable background monitoring. The agent checks portfolio health on a schedule and generates Investment Action reports when issues are detected. It auto-stops after 2 hours.',
  },
  {
    title: 'Try It',
    body: 'Click a suggestion chip below the chat input to start your first query. Alerts in the dashboard are also clickable -- they pre-fill a deep analysis investigation.',
  },
]

export default function DemoGuide({ onClose }) {
  const [step, setStep] = useState(0)
  const current = STEPS[step]
  const isLast = step === STEPS.length - 1

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-slate-800 border border-slate-600/50 rounded-2xl shadow-2xl max-w-md w-full mx-4 p-6">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-slate-500">{step + 1} / {STEPS.length}</span>
          <button onClick={onClose} className="text-slate-500 hover:text-white text-sm">Skip</button>
        </div>
        <h3 className="text-lg font-semibold text-warm-white mb-2">{current.title}</h3>
        <p className="text-sm text-slate-300 leading-relaxed mb-6">{current.body}</p>
        <div className="flex items-center justify-between">
          <button
            onClick={() => setStep(s => s - 1)}
            disabled={step === 0}
            className="px-4 py-2 text-sm text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Back
          </button>
          <div className="flex gap-1.5">
            {STEPS.map((_, i) => (
              <div key={i} className={`w-1.5 h-1.5 rounded-full transition-colors ${i === step ? 'bg-teal-400' : 'bg-slate-600'}`} />
            ))}
          </div>
          {isLast ? (
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium bg-teal-500 text-slate-900 rounded-lg hover:bg-teal-400 transition-colors"
            >
              Get Started
            </button>
          ) : (
            <button
              onClick={() => setStep(s => s + 1)}
              className="px-4 py-2 text-sm font-medium bg-teal-500 text-slate-900 rounded-lg hover:bg-teal-400 transition-colors"
            >
              Next
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
