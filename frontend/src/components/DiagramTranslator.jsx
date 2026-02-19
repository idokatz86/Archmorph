import React, { useState, useRef } from 'react';
import Prism from 'prismjs';
import {
  Upload, ChevronRight, BarChart3, Download, FileCode,
  AlertTriangle, CheckCircle, XCircle, ArrowRight,
  HelpCircle, Eye, Info, Loader2, X, Check,
  FileText, Send, Sparkles, Bot, RotateCcw, Plus,
} from 'lucide-react';
import { Badge, Button, Card } from './ui';
import { API_BASE } from '../constants';

export default function DiagramTranslator() {
  const [step, setStep] = useState('upload');
  const [diagramId, setDiagramId] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState({});
  const [iacCode, setIacCode] = useState(null);
  const [iacFormat, setIacFormat] = useState('terraform');
  const [costEstimate, setCostEstimate] = useState(null);
  const [exportLoading, setExportLoading] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [analyzeProgress, setAnalyzeProgress] = useState([]);
  const fileInputRef = useRef(null);

  // IaC Chat state
  const [iacChatOpen, setIacChatOpen] = useState(false);
  const [iacChatMessages, setIacChatMessages] = useState([
    { role: 'assistant', content: 'Hi! I\'m your **IaC Assistant**. I can help you modify your Terraform/Bicep code. Try asking me to:\n\n- Add VNet with subnets and NSGs\n- Configure public/private IPs\n- Add storage accounts\n- Apply naming conventions\n- Set up monitoring & diagnostics\n- Add Key Vault access policies\n\nWhat would you like to change?' },
  ]);
  const [iacChatInput, setIacChatInput] = useState('');
  const [iacChatLoading, setIacChatLoading] = useState(false);
  const iacChatEndRef = useRef(null);
  const iacChatInputRef = useRef(null);

  // HLD state
  const [hldData, setHldData] = useState(null);
  const [hldLoading, setHldLoading] = useState(false);
  const [hldTab, setHldTab] = useState('overview');

  // ── Upload & Analyze ──
  const handleUpload = async (file) => {
    setError(null);
    setStep('analyzing');
    setAnalyzeProgress([]);

    const addStep = async (msg, delay = 200 + Math.random() * 150) => {
      await new Promise(r => setTimeout(r, delay));
      setAnalyzeProgress(prev => [...prev, msg]);
    };

    await addStep('Connecting to analysis engine...');

    // Simulated progress messages shown while waiting for AI
    const waitingMessages = [
      'Scanning diagram components...',
      'Identifying cloud services and icons...',
      'Detecting networking topology...',
      'Analyzing compute and storage layers...',
      'Evaluating security boundaries...',
      'Mapping data flow connections...',
      'Reviewing architecture patterns...',
      'Cross-referencing service catalog...',
      'Validating service dependencies...',
      'Finalizing architecture analysis...',
    ];

    try {
      const formData = new FormData();
      formData.append('file', file);

      await addStep('Uploading diagram...');
      const uploadRes = await fetch(`${API_BASE}/projects/demo-project/diagrams`, { method: 'POST', body: formData });
      const { diagram_id } = await uploadRes.json();
      setDiagramId(diagram_id);

      await addStep('Analyzing architecture with GPT-4o Vision...');

      // Start simulated progress while waiting for the AI response
      let msgIndex = 0;
      const progressInterval = setInterval(() => {
        if (msgIndex < waitingMessages.length) {
          setAnalyzeProgress(prev => [...prev, waitingMessages[msgIndex]]);
          msgIndex++;
        }
      }, 2500 + Math.random() * 1500);

      const analyzeRes = await fetch(`${API_BASE}/diagrams/${diagram_id}/analyze`, { method: 'POST' });
      clearInterval(progressInterval);
      const result = await analyzeRes.json();

      if (analyzeRes.status === 422 && result?.detail?.error === 'not_architecture_diagram') {
        const msg = result.detail.message || 'The uploaded image is not a valid architecture diagram.';
        const imageType = result.detail.classification?.image_type || 'unknown';
        setError(`🚫 ${msg}\n\nDetected image type: "${imageType}". Please upload a cloud architecture diagram (AWS, GCP, or similar).`);
        setStep('upload');
        return;
      }

      if (!analyzeRes.ok) {
        throw new Error(result?.detail || 'Analysis failed');
      }

      // Show dynamic zone-by-zone progress from the real analysis result
      const provider = (result.source_provider || 'aws').toUpperCase();
      for (const zone of (result.zones || [])) {
        const svcNames = (zone.services || []).map(s => {
          if (typeof s === 'string') return s;
          return s.source || s.aws || s.gcp || s.source_service || s.name || '';
        }).filter(Boolean).slice(0, 3);
        const svcLabel = svcNames.length > 0 ? ` (${svcNames.join(', ')})` : '';
        await addStep(`Zone ${zone.number || zone.id}: ${zone.name}${svcLabel}...`);
      }

      await addStep(`Mapping ${provider} services to Azure equivalents...`);
      await addStep('Calculating confidence scores...');
      await addStep('Analysis complete. ✓', 600);

      // Brief pause so user sees "Analysis complete" before transitioning
      await new Promise(r => setTimeout(r, 800));

      setAnalysis(result);

      const qRes = await fetch(`${API_BASE}/diagrams/${diagram_id}/questions`, { method: 'POST' });
      const qData = await qRes.json();
      setQuestions(qData.questions || []);

      const defaults = {};
      (qData.questions || []).forEach(q => { defaults[q.id] = q.default; });
      setAnswers(defaults);

      setStep('questions');
    } catch (err) {
      setError(err.message);
      setStep('upload');
    }
  };

  const handleApplyAnswers = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/diagrams/${diagramId}/apply-answers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(answers),
      });
      const refined = await res.json();
      setAnalysis(refined);
      setStep('results');
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  };

  const handleGenerateIac = async (fmt) => {
    setLoading(true);
    setIacFormat(fmt);
    try {
      const [iacRes, costRes] = await Promise.all([
        fetch(`${API_BASE}/diagrams/${diagramId}/generate?format=${fmt}`, { method: 'POST' }),
        fetch(`${API_BASE}/diagrams/${diagramId}/cost-estimate`),
      ]);
      const iacData = await iacRes.json();
      const costData = await costRes.json();
      setIacCode(iacData.code);
      setCostEstimate(costData);
      setStep('iac');
      setTimeout(() => Prism.highlightAll(), 100);
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  };

  const handleExportDiagram = async (format) => {
    setExportLoading(prev => ({ ...prev, [format]: true }));
    try {
      const res = await fetch(`${API_BASE}/diagrams/${diagramId}/export-diagram?format=${format}`, { method: 'POST' });
      const data = await res.json();
      const content = typeof data.content === 'string' ? data.content : JSON.stringify(data.content, null, 2);
      const blob = new Blob([content], { type: 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = data.filename || `archmorph-diagram.${format === 'excalidraw' ? 'excalidraw' : format === 'drawio' ? 'drawio' : 'vdx'}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(`Export failed: ${err.message}`);
    }
    setExportLoading(prev => ({ ...prev, [format]: false }));
  };

  const handleIacChat = async () => {
    const text = iacChatInput.trim();
    if (!text || iacChatLoading) return;
    setIacChatInput('');
    setIacChatMessages(prev => [...prev, { role: 'user', content: text }]);
    setIacChatLoading(true);
    try {
      const res = await fetch(`${API_BASE}/diagrams/${diagramId}/iac-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, code: iacCode || '', format: iacFormat }),
      });
      const data = await res.json();
      setIacChatMessages(prev => [...prev, {
        role: 'assistant',
        content: data.reply || data.message || 'Done.',
        changes: data.changes_summary || [],
        services: data.services_added || [],
      }]);
      if (data.code && !data.error) {
        setIacCode(data.code);
        setTimeout(() => Prism.highlightAll(), 100);
      }
    } catch {
      setIacChatMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, couldn\'t connect to the IaC assistant.' }]);
    }
    setIacChatLoading(false);
    setTimeout(() => iacChatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  const handleGenerateHld = async () => {
    setHldLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/diagrams/${diagramId}/generate-hld`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || `HLD generation failed (${res.status})`);
      if (data.hld) setHldData(data);
    } catch (err) {
      setError('HLD generation failed: ' + err.message);
    }
    setHldLoading(false);
  };

  const reset = () => {
    setStep('upload');
    setDiagramId(null);
    setAnalysis(null);
    setQuestions([]);
    setAnswers({});
    setIacCode(null);
    setCostEstimate(null);
    setHldData(null);
    setError(null);
    setAnalyzeProgress([]);
  };

  return (
    <div className="space-y-6">
      {/* Progress Steps */}
      <div className="flex items-center justify-center gap-2 text-xs font-medium">
        {[
          { id: 'upload', label: 'Upload', canNav: true },
          { id: 'analyzing', label: 'Analyzing', canNav: false },
          { id: 'questions', label: 'Customize', canNav: !!analysis },
          { id: 'results', label: 'Results', canNav: !!analysis },
          { id: 'iac', label: 'IaC Code', canNav: !!iacCode },
        ].map((s, i, arr) => {
          const isActive = step === s.id;
          const isPast = arr.findIndex(x => x.id === step) > i;
          const clickable = s.canNav && !isActive && step !== 'analyzing';
          return (
          <React.Fragment key={s.id}>
            {clickable ? (
              <button
                type="button"
                onClick={() => setStep(s.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full transition-all duration-150 cursor-pointer border-none bg-transparent select-none ${
                  isPast ? 'text-cta hover:bg-cta/15 hover:scale-105' : 'text-text-muted hover:bg-cta/10 hover:text-cta'
                }`}
                title={`Go to ${s.label}`}
              >
                {isPast ? <CheckCircle className="w-3.5 h-3.5" /> : <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">{i + 1}</span>}
                <span className="hidden sm:inline underline decoration-dotted underline-offset-2">{s.label}</span>
              </button>
            ) : (
              <div
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full transition-colors ${
                  isActive ? 'bg-cta/15 text-cta' :
                  isPast ? 'text-cta' : 'text-text-muted'
                }`}
              >
                {isPast ? <CheckCircle className="w-3.5 h-3.5" /> : <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">{i + 1}</span>}
                <span className="hidden sm:inline">{s.label}</span>
              </div>
            )}
            {i < arr.length - 1 && <ChevronRight className="w-4 h-4 text-text-muted" />}
          </React.Fragment>
        );})}
      </div>

      {error && (
        <Card className="p-4 border-danger/30">
          <div className="flex items-center gap-3">
            <XCircle className="w-5 h-5 text-danger shrink-0" />
            <p className="text-sm text-danger">{error}</p>
            <button onClick={() => setError(null)} className="ml-auto cursor-pointer" aria-label="Dismiss error"><X className="w-4 h-4 text-text-muted" /></button>
          </div>
        </Card>
      )}

      {/* Step: Upload */}
      {step === 'upload' && (
        <Card className="p-12">
          <div className="text-center max-w-lg mx-auto">
            <div className="w-16 h-16 rounded-2xl bg-cta/10 flex items-center justify-center mx-auto mb-6">
              <Upload className="w-8 h-8 text-cta" />
            </div>
            <h2 className="text-2xl font-bold text-text-primary mb-2">Upload Architecture Diagram</h2>
            <p className="text-sm text-text-secondary mb-8">
              Upload your AWS or GCP architecture diagram. We will analyze it and translate every service to Azure with IaC generation.
            </p>
            <input ref={fileInputRef} type="file" accept="image/*,.pdf,.svg" onChange={e => e.target.files[0] && handleUpload(e.target.files[0])} className="hidden" aria-label="Select architecture diagram file" />
            <Button onClick={() => fileInputRef.current?.click()} variant="primary" size="lg" icon={Upload}>
              Select Diagram File
            </Button>
            <p className="text-xs text-text-muted mt-4">Supports PNG, JPG, SVG, PDF</p>
          </div>
        </Card>
      )}

      {/* Step: Analyzing */}
      {step === 'analyzing' && (
        <Card className="p-8">
          <div className="max-w-2xl mx-auto">
            <div className="flex items-center gap-3 mb-6">
              <Loader2 className="w-6 h-6 text-cta animate-spin" />
              <h2 className="text-xl font-bold text-text-primary">Analyzing Architecture...</h2>
            </div>
            <div className="space-y-1 font-mono text-xs">
              {analyzeProgress.map((msg, i) => (
                <div key={i} className="flex items-center gap-2 text-text-secondary animate-fade-in">
                  <CheckCircle className="w-3.5 h-3.5 text-cta shrink-0" />
                  <span>{msg}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* Step: Questions */}
      {step === 'questions' && (
        <div className="space-y-6">
          <Card className="p-6">
            <div className="flex items-center gap-3 mb-2">
              <HelpCircle className="w-6 h-6 text-cta" />
              <h2 className="text-xl font-bold text-text-primary">Customize Your Azure Architecture</h2>
            </div>
            <p className="text-sm text-text-secondary">
              We detected {analysis?.services_detected || 0} {(analysis?.source_provider || 'aws').toUpperCase()} services across {analysis?.zones?.length || 0} zones.
              Answer these questions to tailor the Azure translation to your needs.
            </p>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {questions.map(q => (
              <Card key={q.id} className="p-4 space-y-3">
                <div className="flex items-start gap-2">
                  <Badge>{q.category?.replace(/_/g, ' ')}</Badge>
                  {q.impact && <span className="text-[10px] text-text-muted uppercase">{q.impact}</span>}
                </div>
                <p className="text-sm font-medium text-text-primary">{q.question}</p>
                {q.type === 'single_choice' && (
                  <div className="space-y-1.5">
                    {q.options?.map(raw => {
                      const opt = typeof raw === 'string' ? { value: raw, label: raw } : raw;
                      return (
                        <label key={opt.value} className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary cursor-pointer transition-colors">
                          <input type="radio" name={q.id} value={opt.value} checked={answers[q.id] === opt.value} onChange={() => setAnswers(prev => ({ ...prev, [q.id]: opt.value }))} className="w-4 h-4 accent-cta cursor-pointer" />
                          <div>
                            <span className="text-sm text-text-primary">{opt.label}</span>
                            {opt.description && <p className="text-xs text-text-muted">{opt.description}</p>}
                          </div>
                        </label>
                      );
                    })}
                  </div>
                )}
                {(q.type === 'multi_choice' || q.type === 'multiple_choice') && (
                  <div className="space-y-1.5">
                    {q.options?.map(raw => {
                      const opt = typeof raw === 'string' ? { value: raw, label: raw } : raw;
                      return (
                        <label key={opt.value} className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary cursor-pointer transition-colors">
                          <input type="checkbox" checked={(answers[q.id] || []).includes(opt.value)} onChange={e => {
                            const current = answers[q.id] || [];
                            setAnswers(prev => ({ ...prev, [q.id]: e.target.checked ? [...current, opt.value] : current.filter(v => v !== opt.value) }));
                          }} className="w-4 h-4 accent-cta cursor-pointer" />
                          <span className="text-sm text-text-primary">{opt.label}</span>
                        </label>
                      );
                    })}
                  </div>
                )}
                {(q.type === 'boolean' || q.type === 'yes_no') && (
                  <div className="flex items-center gap-3">
                    {['yes', 'no'].map(v => (
                      <label key={v} className="flex items-center gap-2 p-2 rounded-lg hover:bg-secondary cursor-pointer transition-colors">
                        <input type="radio" name={q.id} value={v} checked={answers[q.id] === v} onChange={() => setAnswers(prev => ({ ...prev, [q.id]: v }))} className="w-4 h-4 accent-cta cursor-pointer" />
                        <span className="text-sm text-text-primary capitalize">{v}</span>
                      </label>
                    ))}
                  </div>
                )}
              </Card>
            ))}
          </div>

          <div className="flex items-center justify-between">
            <Button onClick={() => { setStep('results'); }} variant="ghost" icon={ChevronRight}>Skip Customization</Button>
            <Button onClick={handleApplyAnswers} loading={loading} icon={Check}>Apply and View Results</Button>
          </div>
        </div>
      )}

      {/* Step: Results */}
      {step === 'results' && analysis && (
        <div className="space-y-6">
          <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-xl font-bold text-text-primary">{analysis.diagram_type}</h2>
                <p className="text-sm text-text-secondary mt-1">
                  {analysis.services_detected} services mapped across {analysis.zones?.length} zones
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={analysis.source_provider || 'aws'}>{(analysis.source_provider || 'aws').toUpperCase()}</Badge>
                <ArrowRight className="w-4 h-4 text-text-muted" />
                <Badge variant="azure">Azure</Badge>
              </div>
            </div>

            {analysis.confidence_summary && (
              <div className="grid grid-cols-4 gap-3 mt-4">
                {[
                  { label: 'High', value: analysis.confidence_summary.high, color: 'text-cta' },
                  { label: 'Medium', value: analysis.confidence_summary.medium, color: 'text-warning' },
                  { label: 'Low', value: analysis.confidence_summary.low, color: 'text-danger' },
                  { label: 'Average', value: `${(analysis.confidence_summary.average * 100).toFixed(0)}%`, color: 'text-info' },
                ].map(c => (
                  <div key={c.label} className="bg-surface rounded-lg p-3 text-center">
                    <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
                    <p className="text-xs text-text-muted mt-1">{c.label} Confidence</p>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Zones */}
          <div className="space-y-3">
            {analysis.zones?.map(zone => {
              const zoneMappings = analysis.mappings?.filter(m => m.notes?.includes(`Zone ${zone.id}`)) || [];
              return (
                <Card key={zone.id} className="overflow-hidden">
                  <div className="px-4 py-3 bg-secondary/50 border-b border-border flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-6 h-6 rounded bg-cta/15 text-cta text-xs font-bold flex items-center justify-center">{zone.id}</span>
                      <h3 className="text-sm font-semibold text-text-primary">{zone.name}</h3>
                    </div>
                    <span className="text-xs text-text-muted">{Array.isArray(zone.services) ? zone.services.length : zone.services} services</span>
                  </div>
                  {zoneMappings.length > 0 && (
                    <div className="divide-y divide-border">
                      {zoneMappings.map((m, i) => (
                        <div key={i} className="px-4 py-3 flex items-center gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className={`text-sm font-medium ${analysis.source_provider === 'gcp' ? 'text-[#EA4335]' : 'text-[#FF9900]'}`}>{m.source_service}</span>
                              <ArrowRight className="w-3.5 h-3.5 text-text-muted shrink-0" />
                              <span className="text-sm text-info font-medium">{m.azure_service}</span>
                            </div>
                          </div>
                          <Badge variant={m.confidence >= 0.9 ? 'high' : m.confidence >= 0.8 ? 'medium' : 'low'}>
                            {(m.confidence * 100).toFixed(0)}%
                          </Badge>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>

          {/* Warnings */}
          {analysis.warnings?.length > 0 && (
            <Card className="p-4">
              <h3 className="text-sm font-semibold text-warning flex items-center gap-2 mb-3">
                <AlertTriangle className="w-4 h-4" />
                Warnings and Recommendations
              </h3>
              <div className="space-y-2">
                {analysis.warnings.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                    <Info className="w-3.5 h-3.5 text-warning shrink-0 mt-0.5" />
                    <span>{w}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Export + Generate */}
          <Card className="p-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div>
                <h3 className="text-sm font-semibold text-text-primary mb-1">Export Architecture Diagram</h3>
                <p className="text-xs text-text-muted">Download in your preferred format with Azure stencils</p>
              </div>
              <div className="flex items-center gap-2">
                {[
                  { id: 'excalidraw', label: 'Excalidraw' },
                  { id: 'drawio', label: 'Draw.io' },
                  { id: 'vsdx', label: 'Visio' },
                ].map(f => (
                  <Button key={f.id} onClick={() => handleExportDiagram(f.id)} variant="secondary" size="sm" loading={exportLoading[f.id]} icon={Download}>
                    {f.label}
                  </Button>
                ))}
              </div>
            </div>
          </Card>

          <div className="flex items-center justify-between">
            <Button onClick={() => setStep('questions')} variant="ghost" icon={HelpCircle}>Back to Questions</Button>
            <div className="flex items-center gap-2">
              <Button onClick={() => handleGenerateIac('terraform')} loading={loading && iacFormat === 'terraform'} icon={FileCode}>Generate Terraform</Button>
              <Button onClick={() => handleGenerateIac('bicep')} variant="secondary" loading={loading && iacFormat === 'bicep'} icon={FileCode}>Generate Bicep</Button>
              <Button onClick={handleGenerateHld} loading={hldLoading} variant="secondary" icon={Sparkles}>Generate HLD</Button>
            </div>
          </div>

          {/* HLD Document */}
          {hldData && (
            <Card className="p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <Sparkles className="w-6 h-6 text-cta" />
                  <div>
                    <h2 className="text-xl font-bold text-text-primary">{hldData.hld?.title || 'High-Level Design'}</h2>
                    <p className="text-xs text-text-muted">AI-generated architecture document</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button onClick={() => { navigator.clipboard.writeText(hldData.markdown || ''); }} variant="ghost" size="sm" icon={FileText}>Copy MD</Button>
                  <Button onClick={() => {
                    const blob = new Blob([hldData.markdown || ''], { type: 'text/markdown' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a'); a.href = url; a.download = 'archmorph-hld.md'; a.click();
                    URL.revokeObjectURL(url);
                  }} variant="ghost" size="sm" icon={Download}>Download</Button>
                  <Button onClick={() => {
                    const blob = new Blob([JSON.stringify(hldData.hld, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a'); a.href = url; a.download = 'archmorph-hld.json'; a.click();
                    URL.revokeObjectURL(url);
                  }} variant="ghost" size="sm" icon={Download}>JSON</Button>
                </div>
              </div>

              {/* HLD Tabs */}
              <div className="flex gap-1 mb-4 border-b border-border pb-2">
                {[
                  { id: 'overview', label: 'Overview' },
                  { id: 'services', label: 'Services' },
                  { id: 'networking', label: 'Networking' },
                  { id: 'security', label: 'Security' },
                  { id: 'finops', label: 'FinOps' },
                  { id: 'migration', label: 'Migration' },
                  { id: 'waf', label: 'WAF' },
                ].map(t => (
                  <button key={t.id} onClick={() => setHldTab(t.id)}
                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
                      hldTab === t.id ? 'bg-cta/15 text-cta' : 'text-text-muted hover:text-text-primary'
                    }`}>{t.label}</button>
                ))}
              </div>

              <div className="text-sm text-text-secondary space-y-3 max-h-[600px] overflow-y-auto">
                {hldTab === 'overview' && (
                  <div className="space-y-3">
                    <p className="whitespace-pre-wrap">{hldData.hld?.executive_summary}</p>
                    {hldData.hld?.architecture_overview && (
                      <div className="p-4 bg-surface rounded-xl border border-border">
                        <p className="text-xs font-semibold text-text-primary mb-2">Architecture Style: {hldData.hld.architecture_overview.architecture_style}</p>
                        <p className="text-xs">{hldData.hld.architecture_overview.description}</p>
                      </div>
                    )}
                    {hldData.hld?.region_strategy && (
                      <div className="p-4 bg-surface rounded-xl border border-border">
                        <p className="text-xs font-semibold text-text-primary mb-1">Region Strategy</p>
                        <p className="text-xs">Primary: {hldData.hld.region_strategy.primary_region} | DR: {hldData.hld.region_strategy.dr_region}</p>
                      </div>
                    )}
                    {hldData.hld?.azure_caf_alignment && (
                      <div className="p-4 bg-surface rounded-xl border border-border">
                        <p className="text-xs font-semibold text-text-primary mb-1">Azure CAF Alignment</p>
                        <p className="text-xs">Naming: {hldData.hld.azure_caf_alignment.naming_convention}</p>
                        <p className="text-xs">Landing Zone: {hldData.hld.azure_caf_alignment.landing_zone}</p>
                      </div>
                    )}
                  </div>
                )}

                {hldTab === 'services' && hldData.hld?.services && (
                  <div className="space-y-3">
                    {hldData.hld.services.map((svc, i) => (
                      <div key={i} className="p-4 bg-surface rounded-xl border border-border">
                        <div className="flex items-center justify-between mb-2">
                          <h4 className="text-xs font-semibold text-text-primary">{svc.azure_service}</h4>
                          {svc.source_service && <span className="text-[10px] px-2 py-0.5 bg-warning/10 text-warning rounded-full">from {svc.source_service}</span>}
                        </div>
                        <p className="text-xs mb-2">{svc.description}</p>
                        <p className="text-[10px] text-cta font-medium mb-1">Why: {svc.justification}</p>
                        <div className="flex flex-wrap gap-2 text-[10px] text-text-muted">
                          {svc.tier_recommendation && <span>Tier: {svc.tier_recommendation}</span>}
                          {svc.sla && <span>SLA: {svc.sla}</span>}
                          {svc.estimated_monthly_cost && <span>Cost: {svc.estimated_monthly_cost}</span>}
                        </div>
                        {svc.documentation_url && (
                          <a href={svc.documentation_url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-cta hover:underline mt-1 inline-block">Documentation →</a>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {hldTab === 'networking' && hldData.hld?.networking_design && (
                  <div className="space-y-2 p-4 bg-surface rounded-xl border border-border">
                    <p className="text-xs"><strong>Topology:</strong> {hldData.hld.networking_design.topology}</p>
                    <p className="text-xs"><strong>VNet:</strong> {hldData.hld.networking_design.vnet_design}</p>
                    <p className="text-xs"><strong>DNS:</strong> {hldData.hld.networking_design.dns_strategy}</p>
                    {hldData.hld.networking_design.security_controls && (
                      <p className="text-xs"><strong>Controls:</strong> {hldData.hld.networking_design.security_controls.join(', ')}</p>
                    )}
                  </div>
                )}

                {hldTab === 'security' && hldData.hld?.security_design && (
                  <div className="space-y-2 p-4 bg-surface rounded-xl border border-border">
                    <p className="text-xs"><strong>Identity:</strong> {hldData.hld.security_design.identity}</p>
                    <p className="text-xs"><strong>Data:</strong> {hldData.hld.security_design.data_protection}</p>
                    <p className="text-xs"><strong>Network:</strong> {hldData.hld.security_design.network_security}</p>
                    <p className="text-xs"><strong>Secrets:</strong> {hldData.hld.security_design.secrets_management}</p>
                  </div>
                )}

                {hldTab === 'finops' && hldData.hld?.finops && (
                  <div className="space-y-2 p-4 bg-surface rounded-xl border border-border">
                    <p className="text-xs font-semibold text-cta">Total: {hldData.hld.finops.total_estimated_monthly_cost}</p>
                    {hldData.hld.finops.cost_optimization_recommendations?.map((r, i) => (
                      <p key={i} className="text-xs flex items-start gap-1"><span className="text-cta">•</span> {r}</p>
                    ))}
                    {hldData.hld.finops.reserved_instances_candidates?.length > 0 && (
                      <p className="text-xs"><strong>RI Candidates:</strong> {hldData.hld.finops.reserved_instances_candidates.join(', ')}</p>
                    )}
                  </div>
                )}

                {hldTab === 'migration' && hldData.hld?.migration_approach && (
                  <div className="space-y-3">
                    <p className="text-xs font-semibold">Strategy: {hldData.hld.migration_approach.strategy}</p>
                    {hldData.hld.migration_approach.phases?.map((p, i) => (
                      <div key={i} className="p-3 bg-surface rounded-xl border border-border">
                        <p className="text-xs font-semibold text-text-primary">Phase {p.phase}: {p.name}</p>
                        <p className="text-[10px] text-text-muted mt-1">{p.description}</p>
                        <p className="text-[10px] mt-1">Duration: {p.duration_weeks} weeks | Services: {p.services?.join(', ')}</p>
                      </div>
                    ))}
                  </div>
                )}

                {hldTab === 'waf' && hldData.hld?.waf_assessment && (
                  <div className="space-y-2 p-4 bg-surface rounded-xl border border-border">
                    {Object.entries(hldData.hld.waf_assessment).map(([pillar, info]) => (
                      <div key={pillar} className="flex items-center justify-between py-1 border-b border-border/50 last:border-0">
                        <span className="text-xs font-medium text-text-primary capitalize">{pillar.replace(/_/g, ' ')}</span>
                        <div className="flex items-center gap-2">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                            info.score === 'High' ? 'bg-cta/15 text-cta' : info.score === 'Medium' ? 'bg-warning/15 text-warning' : 'bg-red-500/15 text-red-400'
                          }`}>{info.score}</span>
                          <span className="text-[10px] text-text-muted max-w-xs truncate">{info.notes}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* Step: IaC Code */}
      {step === 'iac' && iacCode && (
        <div className="space-y-6">

          {/* Cost Estimate — shown first */}
          {costEstimate && (
            <Card className="p-6">
              <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-4">
                <BarChart3 className="w-5 h-5 text-cta" />
                Estimated Monthly Cost
              </h3>
              {costEstimate.region && (
                <p className="text-xs text-text-muted mb-3">
                  Region: <span className="font-medium text-text-secondary">{costEstimate.region}</span>
                  {costEstimate.service_count > 0 && <span className="ml-2">({costEstimate.service_count} services)</span>}
                </p>
              )}
              <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="bg-surface rounded-lg p-3 text-center">
                  <p className="text-lg font-bold text-cta">${costEstimate.total_monthly_estimate?.low?.toLocaleString() || '---'}</p>
                  <p className="text-xs text-text-muted">Low Estimate</p>
                </div>
                <div className="bg-surface rounded-lg p-3 text-center">
                  <p className="text-lg font-bold text-warning">${costEstimate.total_monthly_estimate?.high?.toLocaleString() || '---'}</p>
                  <p className="text-xs text-text-muted">High Estimate</p>
                </div>
              </div>
              {costEstimate.services && (
                <div className="space-y-2 max-h-64 overflow-auto">
                  {costEstimate.services.map((s, i) => (
                    <div key={i} className="flex items-center justify-between py-1.5 border-b border-border last:border-0">
                      <span className="text-xs text-text-secondary">{s.service}</span>
                      <span className="text-xs font-medium text-text-primary">${s.monthly_low} - ${s.monthly_high}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-4 pt-3 border-t border-border flex items-start gap-2">
                <Info className="w-3.5 h-3.5 text-text-muted shrink-0 mt-0.5" />
                <p className="text-[11px] text-text-muted leading-relaxed">
                  These figures are approximate estimates based on Azure Retail Prices and may not reflect your final costs. Actual charges will vary depending on usage, configuration, reserved capacity, and applicable discounts. For an accurate cost projection, please use the <a href="https://azure.microsoft.com/en-us/pricing/calculator/" target="_blank" rel="noopener noreferrer" className="text-cta hover:underline">Azure Pricing Calculator</a>.
                </p>
              </div>
            </Card>
          )}

          {/* IaC Code */}
          <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <FileCode className="w-6 h-6 text-cta" />
                <div>
                  <h2 className="text-xl font-bold text-text-primary">
                    {iacFormat === 'terraform' ? 'Terraform' : 'Bicep'} Code
                  </h2>
                  <p className="text-xs text-text-muted">{iacCode.split('\n').length} lines generated</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button onClick={() => { navigator.clipboard.writeText(iacCode); }} variant="ghost" size="sm" icon={FileText}>Copy</Button>
                <Button onClick={() => {
                  const blob = new Blob([iacCode], { type: 'text/plain' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url; a.download = iacFormat === 'terraform' ? 'main.tf' : 'main.bicep'; a.click();
                  URL.revokeObjectURL(url);
                }} variant="secondary" size="sm" icon={Download}>Download</Button>
              </div>
            </div>
            <div className="bg-surface rounded-lg border border-border overflow-auto max-h-[600px]">
              <pre className="p-4 text-xs leading-relaxed">
                <code className={`language-${iacFormat === 'terraform' ? 'hcl' : 'json'}`}>{iacCode}</code>
              </pre>
            </div>
          </Card>

          {/* IaC Chat Panel */}
          <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-cta/15 flex items-center justify-center">
                  <Sparkles className="w-4 h-4 text-cta" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">IaC Assistant</h3>
                  <p className="text-[10px] text-text-muted">Ask AI to add services, networking, storage & more</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {iacChatOpen && (
                  <button onClick={() => {
                    setIacChatMessages([{ role: 'assistant', content: 'Chat reset. What would you like to change in your IaC code?' }]);
                    if (diagramId) fetch(`${API_BASE}/diagrams/${diagramId}/iac-chat`, { method: 'DELETE' });
                  }} className="p-1.5 hover:bg-surface rounded-lg transition-colors cursor-pointer" title="Reset chat">
                    <RotateCcw className="w-3.5 h-3.5 text-text-muted" />
                  </button>
                )}
                <button onClick={() => {
                  setIacChatOpen(!iacChatOpen);
                  setTimeout(() => iacChatInputRef.current?.focus(), 100);
                }} className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5 ${
                  iacChatOpen ? 'bg-cta/15 text-cta border border-cta/30' : 'bg-surface border border-border text-text-secondary hover:border-cta/40 hover:text-cta'
                }`}>
                  <Bot className="w-3.5 h-3.5" />
                  {iacChatOpen ? 'Close Chat' : 'Open Chat'}
                </button>
              </div>
            </div>

            {!iacChatOpen && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  { label: 'Add VNet & Subnets', msg: 'Add a Virtual Network with 3 subnets: frontend (10.0.1.0/24), backend (10.0.2.0/24), and data (10.0.3.0/24). Include NSGs for each subnet with appropriate rules.' },
                  { label: 'Add Public IPs', msg: 'Add public IP addresses for the load balancer and application gateway. Use Standard SKU with static allocation.' },
                  { label: 'Add Storage Account', msg: 'Add a general-purpose v2 storage account with blob containers, lifecycle management policy, and private endpoint.' },
                  { label: 'Apply Naming Convention', msg: 'Apply Microsoft Cloud Adoption Framework (CAF) naming conventions to ALL resources. Use the pattern: {resource-type}-{project}-{environment}.' },
                  { label: 'Add Monitoring', msg: 'Add Azure Monitor with Log Analytics workspace, diagnostic settings for all resources, and Application Insights.' },
                  { label: 'Add Key Vault Policies', msg: 'Add access policies to the Key Vault for the current user with full key, secret, and certificate permissions. Also add managed identity access for compute resources.' },
                  { label: 'Add Private Endpoints', msg: 'Add private endpoints for all PaaS services (storage accounts, Cosmos DB, SQL, Key Vault). Include Private DNS Zones for each service.' },
                  { label: 'Add Bastion Host', msg: 'Add Azure Bastion with a dedicated AzureBastionSubnet (/26) for secure RDP/SSH access to VMs without public IPs.' },
                ].map((q, i) => (
                  <button key={i} onClick={() => {
                    setIacChatOpen(true);
                    setIacChatInput(q.msg);
                    setTimeout(() => iacChatInputRef.current?.focus(), 100);
                  }} className="px-3 py-2 bg-surface border border-border rounded-lg text-[11px] text-text-secondary hover:border-cta/40 hover:text-cta transition-all cursor-pointer text-left flex items-center gap-1.5">
                    <Plus className="w-3 h-3 shrink-0" />
                    {q.label}
                  </button>
                ))}
              </div>
            )}

            {iacChatOpen && (
              <div className="border border-border rounded-xl overflow-hidden bg-primary">
                <div className="h-80 overflow-y-auto px-4 py-3 space-y-3">
                  {iacChatMessages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[88%] px-3 py-2 rounded-xl text-sm ${
                        msg.role === 'user' ? 'bg-cta/15 text-text-primary rounded-br-sm' : 'bg-secondary text-text-primary rounded-bl-sm'
                      }`}>
                        {msg.content.split('\n').map((line, li) => (
                          <p key={li} className={li > 0 ? 'mt-1.5' : ''}>
                            {line.split(/(\*\*.*?\*\*)/).map((part, pi) => {
                              const bold = part.match(/^\*\*(.*?)\*\*$/);
                              if (bold) return <strong key={pi} className="font-semibold">{bold[1]}</strong>;
                              return part;
                            })}
                          </p>
                        ))}
                        {msg.changes && msg.changes.length > 0 && (
                          <div className="mt-2 pt-2 border-t border-border/50">
                            <p className="text-[10px] font-semibold text-cta mb-1 flex items-center gap-1">
                              <CheckCircle className="w-3 h-3" /> Changes applied:
                            </p>
                            <ul className="space-y-0.5">
                              {msg.changes.map((c, ci) => (
                                <li key={ci} className="text-[10px] text-text-muted flex items-start gap-1"><span className="text-cta mt-0.5">+</span> {c}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {msg.services && msg.services.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {msg.services.map((s, si) => (
                              <span key={si} className="inline-flex items-center px-1.5 py-0.5 text-[9px] font-medium rounded bg-cta/10 text-cta border border-cta/20">{s}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  {iacChatLoading && (
                    <div className="flex justify-start">
                      <div className="bg-secondary px-3 py-2 rounded-xl rounded-bl-sm flex items-center gap-2">
                        <Loader2 className="w-4 h-4 text-cta animate-spin" />
                        <span className="text-xs text-text-muted">Modifying code...</span>
                      </div>
                    </div>
                  )}
                  <div ref={iacChatEndRef} />
                </div>

                <div className="px-3 py-3 border-t border-border bg-secondary/50">
                  <div className="flex items-center gap-2">
                    <input ref={iacChatInputRef} type="text" value={iacChatInput}
                      onChange={e => setIacChatInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleIacChat(); } }}
                      placeholder="Ask to add VNet, storage, IPs, naming conventions..."
                      className="flex-1 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 transition-colors"
                    />
                    <button onClick={handleIacChat} disabled={!iacChatInput.trim() || iacChatLoading}
                      className="p-2 rounded-lg bg-cta hover:bg-cta-hover text-surface disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors">
                      <Send className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </Card>

          <div className="flex items-center justify-between">
            <Button onClick={() => setStep('results')} variant="ghost" icon={Eye}>Back to Results</Button>
            <Button onClick={reset} variant="secondary" icon={Upload}>New Translation</Button>
          </div>
        </div>
      )}
    </div>
  );
}
