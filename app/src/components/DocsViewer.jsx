import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'

export default function DocsViewer({ onClose, initialDoc = 'WALKTHROUGH' }) {
  const [docs, setDocs] = useState([])
  const [selected, setSelected] = useState(initialDoc)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/docs')
      .then(r => r.json())
      .then(d => setDocs(d.docs || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
    fetch(`/api/docs/${selected}`)
      .then(r => r.json())
      .then(d => setContent(d.content || 'No content available.'))
      .catch(() => setContent('Failed to load document.'))
      .finally(() => setLoading(false))
  }, [selected])

  return (
    <div className="fixed inset-0 z-[100] flex">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative m-auto w-full max-w-4xl h-[85vh] bg-slate-800 border border-slate-600/50 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        <div className="px-8 py-4 border-b border-slate-700/50 flex items-center justify-between shrink-0 gap-4">
          {docs.length > 1 ? (
            <select
              value={selected}
              onChange={e => setSelected(e.target.value)}
              className="bg-slate-700 text-warm-white text-sm rounded-lg px-3 py-1.5 border border-slate-600/50 focus:outline-none focus:border-teal-500/50"
            >
              {docs.map(d => (
                <option key={d.name} value={d.name}>{d.title}</option>
              ))}
            </select>
          ) : (
            <h2 className="text-base font-semibold text-warm-white tracking-wide">Documentation</h2>
          )}
          <button onClick={onClose} className="text-slate-400 hover:text-warm-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {loading ? (
            <div className="text-slate-400 text-sm">Loading...</div>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none
              prose-headings:text-warm-white prose-p:text-slate-300
              prose-a:text-amber-400 prose-strong:text-warm-white
              prose-code:text-amber-300 prose-code:bg-slate-700/50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded
              prose-pre:bg-slate-900/60 prose-pre:border prose-pre:border-slate-700/50
              prose-table:text-sm prose-th:text-slate-300 prose-td:text-slate-400
              prose-th:border-slate-600 prose-td:border-slate-700
              prose-blockquote:border-teal-500/40 prose-blockquote:text-slate-300">
              <ReactMarkdown>{content}</ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
