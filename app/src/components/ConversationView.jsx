import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { cn } from '../lib/utils'
import ChartRenderer from './ChartRenderer'

function LoadingDots({ stage }) {
  const stageLabels = {
    starting: 'Checking prerequisites...',
    routing: 'Deciding next step...',
    planning: 'Creating analysis plan...',
    retrieving: 'Gathering evidence from data sources...',
    analyzing: 'Interpreting results...',
    clarifying: 'Asking for clarification...',
    responding: 'Preparing final response...',
  }
  const label = stage ? stageLabels[stage] || stage : null
  return (
    <div className="flex items-center gap-3">
      <div className="flex gap-1.5">
        <div className="w-2 h-2 rounded-full bg-teal-400 loading-dot" />
        <div className="w-2 h-2 rounded-full bg-teal-400 loading-dot" />
        <div className="w-2 h-2 rounded-full bg-teal-400 loading-dot" />
      </div>
      {label && <span className="text-sm text-slate-400">{label}</span>}
    </div>
  )
}

const INTENT_DESCRIPTIONS = {
  query: 'Data lookup detected -- allocated SQL tool only for fast response',
  search: 'Search request detected -- allocated vector search for semantic matching',
  analyze: 'Analysis request detected -- allocated full tool suite (SQL, search, SOPs, write)',
  general: 'General question -- allocated SQL + vector search as default tools',
}

const TOOL_DESCRIPTIONS = {
  execute_sql: 'Execute read-only SQL queries against investment portfolio data',
  search_encounters: 'Search fund documents, memos, and letters using semantic similarity',
  search_fund_documents: 'Search fund documents, memos, and letters using semantic similarity',
  search_sops: 'Search investment policy statements and compliance procedures',
  search_investment_policies: 'Search investment policy statements and compliance procedures',
  analyze_cost_drivers: 'Analyze fund performance drivers, returns, and alpha generation',
  analyze_performance_drivers: 'Analyze fund performance drivers, returns, and alpha generation',
  analyze_los_factors: 'Analyze portfolio concentration risk at fund, sector, and geography level',
  analyze_concentration: 'Analyze portfolio concentration risk at fund, sector, and geography level',
  check_ed_performance: 'Check fund capital calls, distributions, and liquidity',
  check_fund_flows: 'Check fund capital calls, distributions, and liquidity',
  check_staffing_efficiency: 'Analyze sector and geographic exposure shifts over time',
  check_exposure_shifts: 'Analyze sector and geographic exposure shifts over time',
  check_operational_kpis: 'Check portfolio KPIs against IPS thresholds',
  check_portfolio_kpis: 'Check portfolio KPIs against IPS thresholds',
  check_data_freshness: 'Check data pipeline freshness',
  write_analysis: 'Save analysis findings and recommendations',
}

function AgentReasoning({ intent, toolCalls }) {
  const [open, setOpen] = useState(false)
  if (!intent) return null
  return (
    <div className="mt-2">
      <button onClick={() => setOpen(!open)}
        className="text-xs text-slate-500 hover:text-slate-300 transition-colors flex items-center gap-1">
        <span className="font-mono">{open ? '\u25B4' : '\u25BE'}</span>
        {open ? 'Hide' : 'Show'} agent reasoning
      </button>
      {open && (
        <div className="mt-1.5 px-3 py-2 bg-slate-900/60 border border-slate-700/20 rounded-lg text-xs text-slate-400 space-y-1">
          <div><span className="text-slate-500">Intent:</span> <span className="font-mono text-teal-400">{intent}</span>
            {toolCalls?.length > 0 && <> <span className="text-slate-600">-&gt;</span> Tools: <span className="font-mono text-slate-300">{toolCalls.join(', ')}</span></>}
          </div>
          <div className="text-slate-500">{INTENT_DESCRIPTIONS[intent] || ''}</div>
        </div>
      )}
    </div>
  )
}

const AGENT_LABELS = { supervisor: 'Supervisor', planner: 'Planner', retrieval: 'Retrieval', analyst: 'Analyst', respond: 'Respond', clarify: 'Clarify', system: 'System' }

function AgentPipeline({ trace }) {
  const [open, setOpen] = useState(false)
  if (!trace || trace.length === 0) return null
  return (
    <div className="mt-2">
      <button onClick={() => setOpen(!open)}
        className="text-xs text-slate-500 hover:text-slate-300 transition-colors flex items-center gap-1">
        <span className="font-mono">{open ? '\u25B4' : '\u25BE'}</span>
        {open ? 'Hide' : 'Show'} agent pipeline ({trace.length} steps)
      </button>
      {open && (
        <div className="mt-1.5 px-3 py-2 bg-slate-900/60 border border-slate-700/20 rounded-lg text-xs space-y-0.5">
          {trace.map((step, i) => (
            <div key={i} className="flex items-baseline gap-2 text-slate-400">
              <span className="text-slate-600 w-4 text-right flex-shrink-0">{i + 1}.</span>
              <span className="font-mono text-teal-400 flex-shrink-0">{AGENT_LABELS[step.agent] || step.agent}</span>
              <span className="text-slate-600">-&gt;</span>
              <span className="text-slate-300 truncate">{step.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const isErrorMessage = (content) =>
  content?.startsWith('I encountered an error') || content?.startsWith('Deep analysis error')

function Message({ message, isUser, onRetry, chart, plotLoading, onGeneratePlot }) {
  const showPlotButton = !isUser && !isErrorMessage(message.content) && !chart && !plotLoading
  return (
    <div className={cn("message-enter max-w-4xl", isUser ? "ml-auto" : "")}>
      <div className={cn(
        "rounded-2xl px-5 py-4",
        isUser 
          ? "bg-teal-500/20 border border-teal-500/30" 
          : "bg-slate-800/40 border border-slate-700/30"
      )}>
        {isUser ? (
          <p className="whitespace-pre-wrap text-warm-white leading-relaxed">{message.content}</p>
        ) : (
          <div className="prose prose-invert prose-sm max-w-none prose-headings:text-warm-white prose-p:text-warm-white prose-strong:text-teal-400 prose-ul:text-warm-white prose-li:text-warm-white">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>
        )}

        {chart && <ChartRenderer spec={chart} />}

        {chart?.no_data && (
          <p className="mt-2 text-xs text-slate-500 italic">{chart.reason}</p>
        )}

        {plotLoading && (
          <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
            <div className="w-3 h-3 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
            Generating chart...
          </div>
        )}

        {showPlotButton && onGeneratePlot && (
          <button onClick={onGeneratePlot}
            className="mt-3 px-3 py-1.5 text-xs bg-slate-700/50 text-slate-300 border border-slate-600/40 rounded-lg hover:bg-teal-500/20 hover:text-teal-300 hover:border-teal-500/30 transition-all flex items-center gap-1.5"
            title="Use an AI agent to generate a chart from this response">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            Generate Plot
          </button>
        )}

        {!isUser && isErrorMessage(message.content) && onRetry && (
          <button onClick={onRetry}
            className="mt-3 px-4 py-1.5 text-sm bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-lg hover:bg-amber-500/30 transition-all">
            Retry
          </button>
        )}
        
        {message.suggestions && (
          <div className="mt-4 flex flex-wrap gap-2">
            {message.suggestions.map((s, i) => (
              <button key={i} onClick={s.onClick}
                className="px-3 py-1.5 text-sm bg-slate-700/50 text-slate-300 rounded-lg hover:bg-slate-600/50 hover:text-white transition-all">
                {s.label}
              </button>
            ))}
          </div>
        )}
        
        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-3 space-y-1.5">
            <div className="flex flex-wrap gap-1.5">
              {message.tool_calls.map((tool, i) => (
                <span key={i} className="relative group text-xs px-2 py-1 bg-teal-500/20 text-teal-300 rounded-md cursor-help">
                  {tool}
                  <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2.5 py-1.5 bg-slate-900 text-slate-200 text-[11px] rounded-lg shadow-lg border border-slate-700/50 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
                    {TOOL_DESCRIPTIONS[tool] || tool}
                  </span>
                </span>
              ))}
            </div>
            <div className="text-[11px] text-slate-500 leading-relaxed">
              {message.tool_calls.map((tool, i) => (
                <span key={i}>{i > 0 && ' | '}<span className="text-slate-400">{tool}</span>: {TOOL_DESCRIPTIONS[tool] || 'Unknown tool'}</span>
              ))}
            </div>
          </div>
        )}

        {!isUser && message.intent && (
          <AgentReasoning intent={message.intent} toolCalls={message.tool_calls} />
        )}

        {!isUser && message.routing_trace && (
          <AgentPipeline trace={message.routing_trace} />
        )}
      </div>
    </div>
  )
}

function WelcomeMessage({ healthScore }) {
  const getGreeting = () => {
    const hour = new Date().getHours()
    if (hour < 12) return 'Good morning'
    if (hour < 17) return 'Good afternoon'
    return 'Good evening'
  }

  const getHealthColor = (score) => {
    if (!score) return 'text-slate-400'
    if (score >= 80) return 'text-living-green'
    if (score >= 60) return 'text-amber-400'
    return 'text-soft-red'
  }

  const getHealthLabel = (score) => {
    if (!score) return 'Unknown'
    if (score >= 80) return 'Healthy'
    if (score >= 60) return 'Attention needed'
    return 'Critical'
  }

  return (
    <div className="space-y-4 message-enter max-w-4xl">
      <div>
        <p className="text-xl text-warm-white mb-2">
          {getGreeting()}. Portfolio health: {' '}
          <span className={cn("font-semibold", getHealthColor(healthScore?.score))}>
            {healthScore?.score || '--'}/100
          </span>
          {' '}
          <span className="text-slate-400">({getHealthLabel(healthScore?.score)})</span>
        </p>
        
        {healthScore?.summary && (
          <p className="text-slate-300 leading-relaxed">{healthScore.summary}</p>
        )}
        
        {!healthScore?.summary && (
          <p className="text-slate-300 leading-relaxed">
            Ready to help you monitor your investment portfolio, analyze trends, and recommend actions.
            Ask me anything about your portfolio data.
          </p>
        )}
      </div>
    </div>
  )
}

export default function ConversationView({ mode, healthScore, onRefresh, pendingQuery, onPendingQueryHandled }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [loadingStage, setLoadingStage] = useState(null)
  const [chartData, setChartData] = useState({})
  const [plotLoading, setPlotLoading] = useState({})
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const cancelledRef = useRef(false)
  const modeRef = useRef(mode)
  useEffect(() => { modeRef.current = mode }, [mode])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => { scrollToBottom() }, [messages])

  useEffect(() => {
    if (pendingQuery && !isLoading) {
      sendMessage(pendingQuery)
      onPendingQueryHandled?.()
    }
  }, [pendingQuery])

  const sendDeepAnalysis = async (text, history) => {
    cancelledRef.current = false
    const submitRes = await fetch('/api/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, mode: 'rag', history, stream: true }),
    })
    if (!submitRes.ok) throw new Error(`Server error (${submitRes.status})`)
    const { task_id, error } = await submitRes.json()
    if (error || !task_id) {
      if (!cancelledRef.current) setMessages(prev => [...prev, { role: 'assistant', content: `Deep analysis error: ${error || 'No task ID returned'}` }])
      return
    }
    setLoadingStage('starting')
    for (let i = 0; i < 150; i++) {
      if (cancelledRef.current) return
      await new Promise(r => setTimeout(r, 2000))
      if (cancelledRef.current) return
      const pollRes = await fetch(`/api/agent/task/${task_id}`)
      if (!pollRes.ok) continue
      const task = await pollRes.json()
      if (task.status === 'done') {
        if (cancelledRef.current) return
        setLoadingStage(null)
        setMessages(prev => [...prev, {
          role: 'assistant', content: task.response || 'No response',
          tool_calls: task.tool_calls || [],
          routing_trace: task.routing_trace || null,
        }])
        if (task.tool_calls?.includes('write_analysis')) onRefresh?.()
        return
      }
      if (task.status === 'error') {
        if (cancelledRef.current) return
        setLoadingStage(null)
        setMessages(prev => [...prev, { role: 'assistant', content: `Deep analysis error: ${task.error}` }])
        return
      }
      if (task.stage) setLoadingStage(task.stage)
    }
    if (!cancelledRef.current) {
      setLoadingStage(null)
      setMessages(prev => [...prev, { role: 'assistant', content: 'Deep analysis timed out after 5 minutes.' }])
    }
  }

  const sendMessage = async (messageText) => {
    const text = messageText || input.trim()
    if (!text || isLoading) return
    const userMessage = { role: 'user', content: text }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)
    setLoadingStage(null)
    try {
      const history = messages.map(m => ({ role: m.role, content: m.content }))
      if (modeRef.current !== 'quick') {
        await sendDeepAnalysis(text, history)
      } else {
        const res = await fetch('/api/agent/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, mode: 'orchestrator', history }),
        })
        if (!res.ok) throw new Error(`Server error (${res.status})`)
        const data = await res.json()
        const assistantMessage = {
          role: 'assistant', content: data.response || data.error || 'No response',
          tool_calls: data.tool_calls || [], intent: data.intent || null,
        }
        setMessages(prev => [...prev, assistantMessage])
        if (data.tool_calls?.includes('write_analysis')) onRefresh?.()
      }
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', content: `I encountered an error: ${err.message}. Please try again.` }])
    } finally {
      setIsLoading(false)
      setLoadingStage(null)
    }
  }

  const clearChat = () => {
    cancelledRef.current = true
    setMessages([])
    setIsLoading(false)
    setLoadingStage(null)
    setChartData({})
    setPlotLoading({})
  }

  const generatePlot = async (idx) => {
    const msg = messages[idx]
    if (!msg || msg.role === 'user') return
    setPlotLoading(prev => ({ ...prev, [idx]: true }))
    try {
      const history = messages.slice(0, idx + 1).map(m => ({ role: m.role, content: m.content }))
      const res = await fetch('/api/agent/plot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: msg.content, history }),
      })
      const spec = await res.json()
      setChartData(prev => ({ ...prev, [idx]: spec }))
    } catch (err) {
      setChartData(prev => ({ ...prev, [idx]: { no_data: true, reason: err.message } }))
    } finally {
      setPlotLoading(prev => ({ ...prev, [idx]: false }))
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const [suggestions, setSuggestions] = useState([])

  useEffect(() => {
    fetch('/api/suggestions').then(r => r.json()).then(data => {
      setSuggestions((data.suggestions || []).map(s => ({
        label: s.label,
        full: s.query,
        onClick: () => sendMessage(s.query),
      })))
    }).catch(() => {})
  }, [healthScore])

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar px-6 py-8">
        <div className="max-w-5xl mx-auto space-y-6">
          <WelcomeMessage healthScore={healthScore} />
          {messages.map((msg, idx) => {
            const retryHandler = (msg.role === 'assistant' && isErrorMessage(msg.content) && !isLoading)
              ? () => {
                  const lastUserMsg = [...messages].slice(0, idx).reverse().find(m => m.role === 'user')
                  if (lastUserMsg) sendMessage(lastUserMsg.content)
                }
              : null
            const chart = chartData[idx] && !chartData[idx].no_data ? chartData[idx] : (chartData[idx]?.no_data ? chartData[idx] : null)
            return (
              <Message key={idx} message={msg} isUser={msg.role === 'user'}
                onRetry={retryHandler} chart={chart}
                plotLoading={!!plotLoading[idx]}
                onGeneratePlot={() => generatePlot(idx)} />
            )
          })}
          {isLoading && (
            <div className="max-w-4xl">
              <div className="bg-slate-800/40 border border-slate-700/30 rounded-2xl px-5 py-4">
                <LoadingDots stage={loadingStage} />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="flex-shrink-0 border-t border-slate-700/30 bg-slate-900/50 backdrop-blur-sm px-6 py-4">
        <div className="max-w-5xl mx-auto">
          {messages.length === 0 && (
            <div className="flex flex-wrap gap-2 mb-4">
              {suggestions.map((s, i) => (
                <button key={i} onClick={s.onClick} title={s.full}
                  className="px-4 py-2 text-sm bg-slate-800/60 text-slate-300 rounded-xl border border-slate-700/40 hover:bg-slate-700/60 hover:text-white hover:border-teal-500/30 transition-all">
                  {s.label}
                </button>
              ))}
            </div>
          )}
          <div className="flex gap-3">
            <textarea ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
              placeholder="Ask about your portfolio..." rows={1}
              className="flex-1 bg-slate-800/60 border border-slate-700/40 rounded-xl px-5 py-3.5 text-warm-white placeholder-slate-500 resize-none focus:outline-none focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/20 transition-all" />
            <button onClick={() => sendMessage()} disabled={!input.trim() || isLoading}
              className={cn("px-5 rounded-xl font-medium transition-all flex items-center justify-center",
                input.trim() && !isLoading
                  ? "bg-teal-500 text-slate-900 hover:bg-teal-400 shadow-lg shadow-teal-500/25"
                  : "bg-slate-700/50 text-slate-500 cursor-not-allowed"
              )}>
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
          <div className="mt-3 flex items-center justify-center gap-3 text-xs text-slate-500">
            <span>{mode === 'quick' ? 'Quick Query' : 'Deep Analysis'} mode &middot; Press Enter to send</span>
            {messages.length > 0 && (
              <button onClick={clearChat}
                className="text-slate-500 hover:text-red-400 transition-colors">
                Clear chat
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
