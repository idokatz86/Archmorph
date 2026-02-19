import { useState, useRef } from 'react'
import Prism from 'prismjs'
import 'prismjs/components/prism-hcl'
import 'prismjs/themes/prism-tomorrow.css'

const API_BASE = '/api'

// ─────────────────────────────────────────────────────────────
// API Client
// ─────────────────────────────────────────────────────────────
const api = {
  health: () => fetch(`${API_BASE}/health`).then(r => r.json()),
  uploadDiagram: (projectId, file) => {
    const formData = new FormData()
    formData.append('file', file)
    return fetch(`${API_BASE}/projects/${projectId}/diagrams`, {
      method: 'POST',
      body: formData
    }).then(r => r.json())
  },
  analyzeDiagram: (diagramId) => 
    fetch(`${API_BASE}/diagrams/${diagramId}/analyze`, { method: 'POST' }).then(r => r.json()),
  generateIaC: (diagramId, format = 'terraform') =>
    fetch(`${API_BASE}/diagrams/${diagramId}/generate?format=${format}`, { method: 'POST' }).then(r => r.json()),
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
// Main App
// ─────────────────────────────────────────────────────────────
export default function App() {
  const [step, setStep] = useState('upload') // upload | analyzing | results | iac
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [iacCode, setIacCode] = useState(null)
  const [iacFormat, setIacFormat] = useState('terraform')
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)

  const handleFileSelect = (e) => {
    const f = e.target.files[0]
    if (f) {
      setFile(f)
      setPreview(URL.createObjectURL(f))
      setError(null)
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const f = e.dataTransfer.files[0]
    if (f) {
      setFile(f)
      setPreview(URL.createObjectURL(f))
      setError(null)
    }
  }

  const handleAnalyze = async () => {
    if (!file) return
    setStep('analyzing')
    setError(null)
    try {
      // In real app: upload first, then analyze
      const uploaded = await api.uploadDiagram('demo-project', file)
      const result = await api.analyzeDiagram(uploaded.diagram_id || 'demo')
      setAnalysis(result)
      setStep('results')
    } catch (err) {
      setError(err.message || 'Analysis failed')
      setStep('upload')
    }
  }

  const handleGenerateIaC = async () => {
    if (!analysis) return
    try {
      const result = await api.generateIaC(analysis.diagram_id, iacFormat)
      setIacCode(result.code)
      setStep('iac')
    } catch (err) {
      setError(err.message || 'IaC generation failed')
    }
  }

  const handleCopyCode = () => {
    if (iacCode) {
      navigator.clipboard.writeText(iacCode)
    }
  }

  const handleDownload = () => {
    if (iacCode) {
      const blob = new Blob([iacCode], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = iacFormat === 'terraform' ? 'main.tf' : 'main.bicep'
      a.click()
      URL.revokeObjectURL(url)
    }
  }

  const reset = () => {
    setStep('upload')
    setFile(null)
    setPreview(null)
    setAnalysis(null)
    setIacCode(null)
    setError(null)
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-900/50 backdrop-blur">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-3xl">🏛️</span>
            <div>
              <h1 className="text-xl font-bold text-white">Archmorph</h1>
              <p className="text-xs text-slate-400">Cloud Architecture Translator</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="px-3 py-1 bg-amber-500/20 text-amber-400 rounded-full text-xs font-medium">
              Demo Mode
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-6 py-8">
        {error && (
          <div className="mb-6 p-4 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300">
            {error}
          </div>
        )}

        {/* Step: Upload */}
        {step === 'upload' && (
          <div className="bg-slate-800/50 rounded-2xl p-8 border border-slate-700">
            <h2 className="text-2xl font-bold text-white mb-2">Upload Architecture Diagram</h2>
            <p className="text-slate-400 mb-6">
              Upload an AWS or GCP architecture diagram to translate it to Azure equivalents.
            </p>

            <div
              className="border-2 border-dashed border-slate-600 rounded-xl p-12 text-center hover:border-blue-500 transition cursor-pointer"
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/svg+xml,application/pdf"
                onChange={handleFileSelect}
                className="hidden"
              />
              {preview ? (
                <div>
                  <img src={preview} alt="Preview" className="max-h-64 mx-auto rounded-lg mb-4" />
                  <p className="text-white font-medium">{file?.name}</p>
                </div>
              ) : (
                <div>
                  <div className="text-5xl mb-4">📁</div>
                  <p className="text-white font-medium">Drop your diagram here</p>
                  <p className="text-slate-400 text-sm mt-2">PNG, JPG, SVG, or PDF up to 25MB</p>
                </div>
              )}
            </div>

            {file && (
              <button
                onClick={handleAnalyze}
                className="mt-6 w-full py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition"
              >
                🔍 Analyze & Translate
              </button>
            )}

            <div className="mt-8 grid grid-cols-3 gap-4 text-center">
              <div className="p-4 bg-slate-700/50 rounded-lg">
                <div className="text-2xl mb-2">☁️</div>
                <p className="text-white font-medium">AWS → Azure</p>
                <p className="text-slate-400 text-xs">150+ services mapped</p>
              </div>
              <div className="p-4 bg-slate-700/50 rounded-lg">
                <div className="text-2xl mb-2">🌐</div>
                <p className="text-white font-medium">GCP → Azure</p>
                <p className="text-slate-400 text-xs">100+ services mapped</p>
              </div>
              <div className="p-4 bg-slate-700/50 rounded-lg">
                <div className="text-2xl mb-2">📦</div>
                <p className="text-white font-medium">IaC Export</p>
                <p className="text-slate-400 text-xs">Terraform & Bicep</p>
              </div>
            </div>
          </div>
        )}

        {/* Step: Analyzing */}
        {step === 'analyzing' && (
          <div className="bg-slate-800/50 rounded-2xl p-12 border border-slate-700 text-center">
            <div className="animate-spin text-6xl mb-6">⚙️</div>
            <h2 className="text-2xl font-bold text-white mb-2">Analyzing Diagram...</h2>
            <p className="text-slate-400">Using GPT-4 Vision to detect cloud services</p>
          </div>
        )}

        {/* Step: Results */}
        {step === 'results' && analysis && (
          <div className="space-y-6">
            <div className="bg-slate-800/50 rounded-2xl p-6 border border-slate-700">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-2xl font-bold text-white">Service Mappings</h2>
                  <p className="text-slate-400">{analysis.services_detected} services detected</p>
                </div>
                <div className="flex gap-3">
                  <button onClick={reset} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition">
                    ← Back
                  </button>
                  <button onClick={handleGenerateIaC} className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg transition">
                    Generate IaC →
                  </button>
                </div>
              </div>

              <table className="w-full">
                <thead>
                  <tr className="text-left text-slate-400 border-b border-slate-700">
                    <th className="pb-3">Source Service</th>
                    <th className="pb-3">Provider</th>
                    <th className="pb-3">Azure Equivalent</th>
                    <th className="pb-3">Confidence</th>
                    <th className="pb-3">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.mappings.map((m, i) => (
                    <tr key={i} className="border-b border-slate-700/50 text-white">
                      <td className="py-3 font-medium">{m.source_service}</td>
                      <td className="py-3">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          m.source_provider === 'aws' ? 'bg-orange-500/20 text-orange-400' : 'bg-blue-500/20 text-blue-400'
                        }`}>
                          {m.source_provider.toUpperCase()}
                        </span>
                      </td>
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
                <ul className="text-yellow-300/80 text-sm list-disc list-inside">
                  {analysis.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Step: IaC */}
        {step === 'iac' && iacCode && (
          <div className="bg-slate-800/50 rounded-2xl p-6 border border-slate-700">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-2xl font-bold text-white">Generated Infrastructure Code</h2>
                <p className="text-slate-400">Ready to deploy to Azure</p>
              </div>
              <div className="flex gap-3">
                <button onClick={() => setStep('results')} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition">
                  ← Back
                </button>
                <select
                  value={iacFormat}
                  onChange={(e) => setIacFormat(e.target.value)}
                  className="px-4 py-2 bg-slate-700 text-white rounded-lg"
                >
                  <option value="terraform">Terraform</option>
                  <option value="bicep">Bicep</option>
                </select>
                <button onClick={handleCopyCode} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition">
                  📋 Copy
                </button>
                <button onClick={handleDownload} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition">
                  ⬇ Download
                </button>
              </div>
            </div>

            <pre className="bg-slate-900 rounded-lg p-6 overflow-x-auto text-sm">
              <code className="language-hcl text-slate-300">{iacCode}</code>
            </pre>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-700 mt-12 py-6">
        <div className="max-w-6xl mx-auto px-6 text-center text-slate-500 text-sm">
          Archmorph © 2026 · AI-powered Cloud Architecture Translation
        </div>
      </footer>
    </div>
  )
}
