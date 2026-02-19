import { useState, useRef, useEffect, useMemo } from 'react'
import Prism from 'prismjs'
import 'prismjs/components/prism-hcl'
import 'prismjs/themes/prism-tomorrow.css'

const API_BASE = 'https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io/api'

// ─────────────────────────────────────────────────────────────
// API Client
// ─────────────────────────────────────────────────────────────
const api = {
  health: () => fetch(`${API_BASE}/health`).then(r => r.json()),
  uploadDiagram: (projectId, file) => {
    const formData = new FormData()
    formData.append('file', file)
    return fetch(`${API_BASE}/projects/${projectId}/diagrams`, {
      method: 'POST', body: formData
    }).then(r => r.json())
  },
  analyzeDiagram: (diagramId) =>
    fetch(`${API_BASE}/diagrams/${diagramId}/analyze`, { method: 'POST' }).then(r => r.json()),
  generateIaC: (diagramId, format = 'terraform') =>
    fetch(`${API_BASE}/diagrams/${diagramId}/generate?format=${format}`, { method: 'POST' }).then(r => r.json()),
  getServices: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return fetch(`${API_BASE}/services?${qs}`).then(r => r.json())
  },
  getProviders: () => fetch(`${API_BASE}/services/providers`).then(r => r.json()),
  getCategories: () => fetch(`${API_BASE}/services/categories`).then(r => r.json()),
  getMappings: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return fetch(`${API_BASE}/services/mappings?${qs}`).then(r => r.json())
  },
  getStats: () => fetch(`${API_BASE}/services/stats`).then(r => r.json()),
}

// ─────────────────────────────────────────────────────────────
// Provider Styling
// ─────────────────────────────────────────────────────────────
const PROVIDER_STYLES = {
  aws: { label: 'AWS', color: 'bg-orange-500/20 text-orange-400 border-orange-500/30' },
  azure: { label: 'Azure', color: 'bg-blue-500/20 text-blue-400 border-blue-500/30' },
  gcp: { label: 'GCP', color: 'bg-sky-500/20 text-sky-400 border-sky-500/30' },
}

const CATEGORY_ICONS = {
  'Compute': '🖥️', 'Storage': '💾', 'Database': '🗄️', 'Networking': '🌐',
  'Security': '🔒', 'AI/ML': '🧠', 'Analytics': '📊', 'Integration': '🔗',
  'DevTools': '🛠️', 'Management': '⚙️', 'Containers': '📦', 'IoT': '📡',
  'Media': '🎬', 'Migration': '🚀', 'Business': '💼',
}

// ─────────────────────────────────────────────────────────────
// Confidence Badge
// ─────────────────────────────────────────────────────────────
function ConfidenceBadge({ value }) {
  const pct = Math.round(value * 100)
  let color = 'bg-red-100 text-red-800'
  if (pct >= 90) color = 'bg-green-100 text-green-800'
  else if (pct >= 70) color = 'bg-blue-100 text-blue-800'
  else if (pct >= 50) color = 'bg-yellow-100 text-yellow-800'
  return <span className={`px-2 py-1 rounded text-xs font-medium ${color}`}>{pct}%</span>
}

// ─────────────────────────────────────────────────────────────
// Services Browser Component
// ─────────────────────────────────────────────────────────────
function ServicesBrowser() {
  const [services, setServices] = useState([])
  const [mappings, setMappings] = useState([])
  const [stats, setStats] = useState(null)
  const [categories, setCategories] = useState([])
  const [loading, setLoading] = useState(true)
  const [selProvider, setSelProvider] = useState('')
  const [selCategory, setSelCategory] = useState('')
  const [search, setSearch] = useState('')
  const [view, setView] = useState('services')

  useEffect(() => {
    Promise.all([
      api.getServices(),
      api.getMappings(),
      api.getStats(),
      api.getCategories(),
    ]).then(([svc, map, st, cats]) => {
      setServices(svc.services || [])
      setMappings(map.mappings || [])
      setStats(st)
      setCategories(cats.categories || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  const filteredServices = useMemo(() => {
    let result = services
    if (selProvider) result = result.filter(s => s.provider === selProvider)
    if (selCategory) result = result.filter(s => s.category === selCategory)
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(s =>
        s.name.toLowerCase().includes(q) ||
        (s.fullName || '').toLowerCase().includes(q) ||
        (s.description || '').toLowerCase().includes(q)
      )
    }
    return result
  }, [services, selProvider, selCategory, search])

  const filteredMappings = useMemo(() => {
    let result = mappings
    if (selCategory) result = result.filter(m => m.category === selCategory)
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(m =>
        m.aws.toLowerCase().includes(q) ||
        m.azure.toLowerCase().includes(q) ||
        m.gcp.toLowerCase().includes(q) ||
        (m.notes || '').toLowerCase().includes(q)
      )
    }
    return result
  }, [mappings, selCategory, search])

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-2xl p-12 border border-slate-700 text-center">
        <div className="animate-spin text-6xl mb-6">⚙️</div>
        <h2 className="text-2xl font-bold text-white mb-2">Loading Services Catalog...</h2>
        <p className="text-slate-400">Fetching AWS, Azure, and GCP services</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Stats Banner */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4 text-center">
            <div className="text-3xl font-bold text-white">{stats.totalServices}</div>
            <div className="text-xs text-slate-400 mt-1">Total Services</div>
          </div>
          <div className="bg-slate-800/50 border border-orange-500/30 rounded-xl p-4 text-center">
            <div className="text-3xl font-bold text-orange-400">{stats.providers?.aws || 0}</div>
            <div className="text-xs text-slate-400 mt-1">AWS Services</div>
          </div>
          <div className="bg-slate-800/50 border border-blue-500/30 rounded-xl p-4 text-center">
            <div className="text-3xl font-bold text-blue-400">{stats.providers?.azure || 0}</div>
            <div className="text-xs text-slate-400 mt-1">Azure Services</div>
          </div>
          <div className="bg-slate-800/50 border border-sky-500/30 rounded-xl p-4 text-center">
            <div className="text-3xl font-bold text-sky-400">{stats.providers?.gcp || 0}</div>
            <div className="text-xs text-slate-400 mt-1">GCP Services</div>
          </div>
          <div className="bg-slate-800/50 border border-green-500/30 rounded-xl p-4 text-center">
            <div className="text-3xl font-bold text-green-400">{stats.totalMappings}</div>
            <div className="text-xs text-slate-400 mt-1">Cross-Cloud Mappings</div>
          </div>
        </div>
      )}

      {/* Controls */}
      <div className="bg-slate-800/50 rounded-2xl p-4 border border-slate-700">
        <div className="flex flex-col lg:flex-row gap-4">
          <div className="flex gap-2">
            {[
              { key: 'services', label: '📋 All Services' },
              { key: 'mappings', label: '🔄 Cross-Cloud Mappings' },
              { key: 'compare', label: '⚖️ Compare Providers' },
            ].map(v => (
              <button key={v.key} onClick={() => setView(v.key)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition ${view === v.key ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}`}>
                {v.label}
              </button>
            ))}
          </div>
          <div className="flex flex-1 gap-3">
            <input type="text" placeholder="Search services..." value={search} onChange={e => setSearch(e.target.value)}
              className="flex-1 px-4 py-2 bg-slate-700 text-white rounded-lg border border-slate-600 focus:border-blue-500 focus:outline-none text-sm" />
            {view !== 'compare' && (
              <select value={selCategory} onChange={e => setSelCategory(e.target.value)}
                className="px-3 py-2 bg-slate-700 text-white rounded-lg border border-slate-600 text-sm">
                <option value="">All Categories</option>
                {categories.map(c => <option key={c.name} value={c.name}>{CATEGORY_ICONS[c.name] || '📌'} {c.name}</option>)}
              </select>
            )}
            {view === 'services' && (
              <select value={selProvider} onChange={e => setSelProvider(e.target.value)}
                className="px-3 py-2 bg-slate-700 text-white rounded-lg border border-slate-600 text-sm">
                <option value="">All Providers</option>
                <option value="aws">☁️ AWS</option>
                <option value="azure">🔷 Azure</option>
                <option value="gcp">🌐 GCP</option>
              </select>
            )}
          </div>
        </div>
      </div>

      {/* All Services View */}
      {view === 'services' && (
        <div className="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
          <div className="p-4 border-b border-slate-700">
            <h3 className="text-lg font-semibold text-white">
              Services {filteredServices.length !== services.length && `(${filteredServices.length} of ${services.length})`}
            </h3>
          </div>
          <div className="max-h-[600px] overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-slate-800 z-10">
                <tr className="text-left text-slate-400 border-b border-slate-700 text-sm">
                  <th className="p-3">Provider</th><th className="p-3">Service</th><th className="p-3">Full Name</th>
                  <th className="p-3">Category</th><th className="p-3">Description</th>
                </tr>
              </thead>
              <tbody>
                {filteredServices.map((s, i) => (
                  <tr key={s.id + i} className="border-b border-slate-700/50 hover:bg-slate-700/30 text-white text-sm">
                    <td className="p-3">
                      <span className={`px-2 py-1 rounded text-xs font-medium border ${PROVIDER_STYLES[s.provider]?.color || ''}`}>
                        {PROVIDER_STYLES[s.provider]?.label || s.provider}
                      </span>
                    </td>
                    <td className="p-3 font-medium">{s.name}</td>
                    <td className="p-3 text-slate-300">{s.fullName}</td>
                    <td className="p-3 text-slate-400">{CATEGORY_ICONS[s.category] || '📌'} {s.category}</td>
                    <td className="p-3 text-slate-400">{s.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filteredServices.length === 0 && <div className="p-12 text-center text-slate-500">No services match your filters</div>}
          </div>
        </div>
      )}

      {/* Cross-Cloud Mappings View */}
      {view === 'mappings' && (
        <div className="bg-slate-800/50 rounded-2xl border border-slate-700 overflow-hidden">
          <div className="p-4 border-b border-slate-700">
            <h3 className="text-lg font-semibold text-white">
              Cross-Cloud Mappings {filteredMappings.length !== mappings.length && `(${filteredMappings.length} of ${mappings.length})`}
            </h3>
          </div>
          <div className="max-h-[600px] overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-slate-800 z-10">
                <tr className="text-left text-sm border-b border-slate-700">
                  <th className="p-3 text-orange-400">AWS</th>
                  <th className="p-3 text-center text-slate-500">↔</th>
                  <th className="p-3 text-blue-400">Azure</th>
                  <th className="p-3 text-center text-slate-500">↔</th>
                  <th className="p-3 text-sky-400">GCP</th>
                  <th className="p-3 text-slate-400">Category</th>
                  <th className="p-3 text-slate-400">Confidence</th>
                  <th className="p-3 text-slate-400">Notes</th>
                </tr>
              </thead>
              <tbody>
                {filteredMappings.map((m, i) => (
                  <tr key={i} className="border-b border-slate-700/50 hover:bg-slate-700/30 text-sm">
                    <td className="p-3 text-orange-300 font-medium">{m.aws}</td>
                    <td className="p-3 text-center text-slate-600">→</td>
                    <td className="p-3 text-blue-300 font-medium">{m.azure}</td>
                    <td className="p-3 text-center text-slate-600">→</td>
                    <td className="p-3 text-sky-300 font-medium">{m.gcp}</td>
                    <td className="p-3 text-slate-400">{CATEGORY_ICONS[m.category] || '📌'} {m.category}</td>
                    <td className="p-3"><ConfidenceBadge value={m.confidence} /></td>
                    <td className="p-3 text-slate-500 max-w-[200px] truncate">{m.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filteredMappings.length === 0 && <div className="p-12 text-center text-slate-500">No mappings match your filters</div>}
          </div>
        </div>
      )}

      {/* Compare Providers View */}
      {view === 'compare' && (
        <div className="space-y-4">
          {categories.filter(c => !selCategory || c.name === selCategory).map(cat => (
            <div key={cat.name} className="bg-slate-800/50 rounded-xl border border-slate-700 overflow-hidden">
              <div className="p-4 border-b border-slate-700 flex items-center justify-between">
                <h3 className="text-white font-semibold">{CATEGORY_ICONS[cat.name] || '📌'} {cat.name}</h3>
                <div className="flex gap-4 text-xs">
                  <span className="text-orange-400">AWS: {cat.counts.aws}</span>
                  <span className="text-blue-400">Azure: {cat.counts.azure}</span>
                  <span className="text-sky-400">GCP: {cat.counts.gcp}</span>
                </div>
              </div>
              <div className="grid grid-cols-3 divide-x divide-slate-700">
                {['aws', 'azure', 'gcp'].map(provider => (
                  <div key={provider} className="p-3">
                    <div className={`text-xs font-medium mb-2 ${provider === 'aws' ? 'text-orange-400' : provider === 'azure' ? 'text-blue-400' : 'text-sky-400'}`}>
                      {PROVIDER_STYLES[provider].label}
                    </div>
                    <div className="space-y-1">
                      {services
                        .filter(s => s.provider === provider && s.category === cat.name)
                        .filter(s => !search || s.name.toLowerCase().includes(search.toLowerCase()) || s.description.toLowerCase().includes(search.toLowerCase()))
                        .map(s => (
                          <div key={s.id} className="text-xs text-slate-300 py-1 px-2 rounded hover:bg-slate-700/50" title={s.description}>
                            <span className="font-medium">{s.name}</span>
                            <span className="text-slate-500 ml-1 hidden lg:inline">— {s.description}</span>
                          </div>
                        ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Diagram Translator Component
// ─────────────────────────────────────────────────────────────
function DiagramTranslator() {
  const [step, setStep] = useState('upload')
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [iacCode, setIacCode] = useState(null)
  const [iacFormat, setIacFormat] = useState('terraform')
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)

  const handleFileSelect = (e) => { const f = e.target.files[0]; if (f) { setFile(f); setPreview(URL.createObjectURL(f)); setError(null) } }
  const handleDrop = (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) { setFile(f); setPreview(URL.createObjectURL(f)); setError(null) } }
  const handleAnalyze = async () => {
    if (!file) return; setStep('analyzing'); setError(null)
    try {
      const uploaded = await api.uploadDiagram('demo-project', file)
      const result = await api.analyzeDiagram(uploaded.diagram_id || 'demo')
      setAnalysis(result); setStep('results')
    } catch (err) { setError(err.message || 'Analysis failed'); setStep('upload') }
  }
  const handleGenerateIaC = async () => {
    if (!analysis) return
    try { const result = await api.generateIaC(analysis.diagram_id, iacFormat); setIacCode(result.code); setStep('iac') }
    catch (err) { setError(err.message || 'IaC generation failed') }
  }
  const handleCopyCode = () => { if (iacCode) navigator.clipboard.writeText(iacCode) }
  const handleDownload = () => {
    if (!iacCode) return
    const blob = new Blob([iacCode], { type: 'text/plain' }); const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = iacFormat === 'terraform' ? 'main.tf' : 'main.bicep'; a.click(); URL.revokeObjectURL(url)
  }
  const reset = () => { setStep('upload'); setFile(null); setPreview(null); setAnalysis(null); setIacCode(null); setError(null) }

  return (
    <div>
      {error && <div className="mb-6 p-4 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300">{error}</div>}

      {step === 'upload' && (
        <div className="bg-slate-800/50 rounded-2xl p-8 border border-slate-700">
          <h2 className="text-2xl font-bold text-white mb-2">Upload Architecture Diagram</h2>
          <p className="text-slate-400 mb-6">Upload an AWS or GCP architecture diagram to translate it to Azure equivalents.</p>
          <div className="border-2 border-dashed border-slate-600 rounded-xl p-12 text-center hover:border-blue-500 transition cursor-pointer"
            onDrop={handleDrop} onDragOver={e => e.preventDefault()} onClick={() => fileInputRef.current?.click()}>
            <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/svg+xml,application/pdf" onChange={handleFileSelect} className="hidden" />
            {preview ? (
              <div><img src={preview} alt="Preview" className="max-h-64 mx-auto rounded-lg mb-4" /><p className="text-white font-medium">{file?.name}</p></div>
            ) : (
              <div><div className="text-5xl mb-4">📁</div><p className="text-white font-medium">Drop your diagram here</p><p className="text-slate-400 text-sm mt-2">PNG, JPG, SVG, or PDF up to 25MB</p></div>
            )}
          </div>
          {file && <button onClick={handleAnalyze} className="mt-6 w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition">🔍 Analyze & Translate</button>}
        </div>
      )}

      {step === 'analyzing' && (
        <div className="bg-slate-800/50 rounded-2xl p-12 border border-slate-700 text-center">
          <div className="animate-spin text-6xl mb-6">⚙️</div>
          <h2 className="text-2xl font-bold text-white mb-2">Analyzing Diagram...</h2>
          <p className="text-slate-400">Using GPT-4 Vision to detect cloud services</p>
        </div>
      )}

      {step === 'results' && analysis && (
        <div className="space-y-6">
          <div className="bg-slate-800/50 rounded-2xl p-6 border border-slate-700">
            <div className="flex items-center justify-between mb-6">
              <div><h2 className="text-2xl font-bold text-white">Service Mappings</h2><p className="text-slate-400">{analysis.services_detected} services detected</p></div>
              <div className="flex gap-3">
                <button onClick={reset} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition">← Back</button>
                <button onClick={handleGenerateIaC} className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg transition">Generate IaC →</button>
              </div>
            </div>
            <table className="w-full">
              <thead><tr className="text-left text-slate-400 border-b border-slate-700"><th className="pb-3">Source</th><th className="pb-3">Provider</th><th className="pb-3">Azure Equivalent</th><th className="pb-3">Confidence</th><th className="pb-3">Notes</th></tr></thead>
              <tbody>
                {analysis.mappings.map((m, i) => (
                  <tr key={i} className="border-b border-slate-700/50 text-white">
                    <td className="py-3 font-medium">{m.source_service}</td>
                    <td className="py-3"><span className={`px-2 py-1 rounded text-xs font-medium ${m.source_provider === 'aws' ? 'bg-orange-500/20 text-orange-400' : 'bg-sky-500/20 text-sky-400'}`}>{m.source_provider.toUpperCase()}</span></td>
                    <td className="py-3 text-blue-400">{m.azure_service}</td>
                    <td className="py-3"><ConfidenceBadge value={m.confidence} /></td>
                    <td className="py-3 text-slate-400 text-sm">{m.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {analysis.warnings?.length > 0 && (
            <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
              <h3 className="text-yellow-400 font-semibold mb-2">⚠️ Warnings</h3>
              <ul className="text-yellow-300/80 text-sm list-disc list-inside">{analysis.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}
        </div>
      )}

      {step === 'iac' && iacCode && (
        <div className="bg-slate-800/50 rounded-2xl p-6 border border-slate-700">
          <div className="flex items-center justify-between mb-6">
            <div><h2 className="text-2xl font-bold text-white">Generated Infrastructure Code</h2><p className="text-slate-400">Ready to deploy to Azure</p></div>
            <div className="flex gap-3">
              <button onClick={() => setStep('results')} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition">← Back</button>
              <select value={iacFormat} onChange={e => setIacFormat(e.target.value)} className="px-4 py-2 bg-slate-700 text-white rounded-lg"><option value="terraform">Terraform</option><option value="bicep">Bicep</option></select>
              <button onClick={handleCopyCode} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition">📋 Copy</button>
              <button onClick={handleDownload} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition">⬇ Download</button>
            </div>
          </div>
          <pre className="bg-slate-900 rounded-lg p-6 overflow-x-auto text-sm"><code className="language-hcl text-slate-300">{iacCode}</code></pre>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Main App
// ─────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState('services')

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <header className="border-b border-slate-700 bg-slate-900/50 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-3xl">🏛️</span>
            <div><h1 className="text-xl font-bold text-white">Archmorph</h1><p className="text-xs text-slate-400">Cloud Architecture Translator</p></div>
          </div>
          <nav className="flex items-center gap-2">
            <button onClick={() => setPage('services')} className={`px-4 py-2 rounded-lg text-sm font-medium transition ${page === 'services' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}>
              📋 Services Catalog
            </button>
            <button onClick={() => setPage('translator')} className={`px-4 py-2 rounded-lg text-sm font-medium transition ${page === 'translator' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}>
              🔄 Diagram Translator
            </button>
            <span className="ml-2 px-3 py-1 bg-amber-500/20 text-amber-400 rounded-full text-xs font-medium">Demo</span>
          </nav>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {page === 'services' && <ServicesBrowser />}
        {page === 'translator' && <DiagramTranslator />}
      </main>

      <footer className="border-t border-slate-700 mt-12 py-6">
        <div className="max-w-7xl mx-auto px-6 text-center text-slate-500 text-sm">
          Archmorph © 2026 · AI-powered Cloud Architecture Translation · AWS · Azure · GCP
        </div>
      </footer>
    </div>
  )
}
