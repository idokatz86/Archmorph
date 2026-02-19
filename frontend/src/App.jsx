import React, { useState, useEffect, useRef } from 'react';
import Prism from 'prismjs';
import 'prismjs/themes/prism-tomorrow.css';
import {
  CloudCog, Upload, ChevronRight, Search, Filter, BarChart3,
  Download, FileCode, Layers, Zap, Shield, Globe, Server, Database,
  AlertTriangle, CheckCircle, XCircle, ArrowRight,
  HelpCircle, Eye, Code, Activity, Box, Settings, Loader2, X,
  Check, Info, FileText, MessageSquare, Mail, TrendingUp, Send,
} from 'lucide-react';

const API_BASE = 'https://archmorph-api.icyisland-c0dee6ba.northeurope.azurecontainerapps.io/api';

// ═══════════════════════════════════════════════════════════════
// ICON MAP
// ═══════════════════════════════════════════════════════════════
const CATEGORY_ICONS = {
  Compute: Server, Storage: Database, Networking: Globe, Security: Shield,
  Analytics: BarChart3, AI: Zap, Containers: Box, Database: Database,
  Integration: Layers, 'Developer Tools': Code, IoT: Activity,
  Management: Settings, default: CloudCog,
};

function getCategoryIcon(category) {
  return CATEGORY_ICONS[category] || CATEGORY_ICONS.default;
}

// ═══════════════════════════════════════════════════════════════
// BADGE
// ═══════════════════════════════════════════════════════════════
function Badge({ children, variant = 'default' }) {
  const styles = {
    high: 'bg-cta/15 text-cta border-cta/30',
    medium: 'bg-warning/15 text-warning border-warning/30',
    low: 'bg-danger/15 text-danger border-danger/30',
    aws: 'bg-[#FF9900]/15 text-[#FF9900] border-[#FF9900]/30',
    azure: 'bg-info/15 text-info border-info/30',
    gcp: 'bg-[#EA4335]/15 text-[#EA4335] border-[#EA4335]/30',
    default: 'bg-secondary text-text-secondary border-border',
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-md border ${styles[variant] || styles.default}`}>
      {children}
    </span>
  );
}

// ═══════════════════════════════════════════════════════════════
// BUTTON
// ═══════════════════════════════════════════════════════════════
function Button({ children, onClick, variant = 'primary', size = 'md', disabled, loading, icon: Icon, className = '' }) {
  const base = 'inline-flex items-center justify-center gap-2 font-semibold rounded-lg transition-all duration-200 cursor-pointer select-none disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-cta/50';
  const variants = {
    primary: 'bg-cta hover:bg-cta-hover text-surface shadow-lg shadow-cta/20',
    secondary: 'bg-secondary hover:bg-border-light text-text-primary border border-border',
    ghost: 'hover:bg-secondary text-text-secondary hover:text-text-primary',
    danger: 'bg-danger/15 hover:bg-danger/25 text-danger border border-danger/30',
  };
  const sizes = { sm: 'px-3 py-1.5 text-xs', md: 'px-4 py-2 text-sm', lg: 'px-6 py-3 text-base' };
  return (
    <button onClick={onClick} disabled={disabled || loading} className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}>
      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : Icon && <Icon className="w-4 h-4" />}
      {children}
    </button>
  );
}

// ═══════════════════════════════════════════════════════════════
// CARD
// ═══════════════════════════════════════════════════════════════
function Card({ children, className = '', hover = false }) {
  return (
    <div className={`bg-primary border border-border rounded-xl ${hover ? 'hover:border-border-light transition-colors duration-200 cursor-pointer' : ''} ${className}`}>
      {children}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// NAV BAR
// ═══════════════════════════════════════════════════════════════
function Nav({ activeTab, setActiveTab, updateStatus }) {
  return (
    <header className="sticky top-0 z-50 bg-surface/80 backdrop-blur-xl border-b border-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-cta/15 flex items-center justify-center">
              <CloudCog className="w-5 h-5 text-cta" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-text-primary tracking-tight">Archmorph</h1>
              <p className="text-[10px] text-text-muted font-medium uppercase tracking-wider">Cloud Translator</p>
            </div>
          </div>
          <nav className="flex items-center gap-1">
            {[
              { id: 'translator', label: 'Translator', icon: Layers },
              { id: 'services', label: 'Services', icon: Server },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-colors duration-200 cursor-pointer ${
                  activeTab === tab.id
                    ? 'bg-cta/10 text-cta'
                    : 'text-text-secondary hover:text-text-primary hover:bg-secondary'
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            {updateStatus && (
              <div className="flex items-center gap-2 text-xs text-text-muted">
                <div className={`w-2 h-2 rounded-full ${updateStatus.scheduler_running ? 'bg-cta animate-pulse' : 'bg-text-muted'}`} />
                <span>Catalog {updateStatus.scheduler_running ? 'Live' : 'Idle'}</span>
              </div>
            )}
            <Badge variant="azure">v2.0.0</Badge>
          </div>
        </div>
      </div>
    </header>
  );
}

// ═══════════════════════════════════════════════════════════════
// SERVICES BROWSER
// ═══════════════════════════════════════════════════════════════
function ServicesBrowser() {
  const [services, setServices] = useState([]);
  const [stats, setStats] = useState(null);
  const [search, setSearch] = useState('');
  const [provider, setProvider] = useState('all');
  const [category, setCategory] = useState('all');
  const [categories, setCategories] = useState([]);
  const [view, setView] = useState('grid');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/services`).then(r => r.json()),
      fetch(`${API_BASE}/services/stats`).then(r => r.json()),
      fetch(`${API_BASE}/services/categories`).then(r => r.json()),
    ]).then(([svc, st, cats]) => {
      setServices(svc.services || []);
      setStats(st);
      setCategories((cats.categories || []).map(c => typeof c === 'string' ? c : c.name));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const filtered = services.filter(s => {
    if (provider !== 'all' && s.provider !== provider) return false;
    if (category !== 'all' && s.category !== category) return false;
    if (search && !s.name.toLowerCase().includes(search.toLowerCase()) && !s.description?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="w-8 h-8 text-cta animate-spin" />
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Services', value: stats.totalServices, icon: Server },
            { label: 'Cross-Cloud Mappings', value: stats.totalMappings, icon: Layers },
            { label: 'Categories', value: stats.categories, icon: Filter },
            { label: 'Avg Confidence', value: `${(stats.avgConfidence * 100).toFixed(0)}%`, icon: BarChart3 },
          ].map(s => (
            <Card key={s.label} className="p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-cta/10 flex items-center justify-center">
                  <s.icon className="w-5 h-5 text-cta" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-text-primary">{s.value}</p>
                  <p className="text-xs text-text-muted">{s.label}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Filters */}
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
            <input
              type="text"
              placeholder="Search services..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 focus:ring-1 focus:ring-cta/30 transition-colors"
            />
          </div>
          <select value={provider} onChange={e => setProvider(e.target.value)} className="px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary cursor-pointer focus:outline-none focus:border-cta/50">
            <option value="all">All Providers</option>
            <option value="aws">AWS</option>
            <option value="azure">Azure</option>
            <option value="gcp">GCP</option>
          </select>
          <select value={category} onChange={e => setCategory(e.target.value)} className="px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary cursor-pointer focus:outline-none focus:border-cta/50">
            <option value="all">All Categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <div className="flex items-center gap-1 border border-border rounded-lg p-0.5">
            {['grid', 'list'].map(v => (
              <button key={v} onClick={() => setView(v)} className={`p-1.5 rounded cursor-pointer transition-colors ${view === v ? 'bg-cta/15 text-cta' : 'text-text-muted hover:text-text-primary'}`}>
                {v === 'grid' ? <Box className="w-4 h-4" /> : <FileText className="w-4 h-4" />}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-text-muted">{filtered.length} services found</p>
      </Card>

      {/* Service Grid/List */}
      <div className={view === 'grid' ? 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4' : 'space-y-2'}>
        {filtered.slice(0, 60).map((s, i) => {
          const Icon = getCategoryIcon(s.category);
          return view === 'grid' ? (
            <Card key={i} hover className="p-4">
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-secondary flex items-center justify-center shrink-0">
                  <Icon className="w-4 h-4 text-text-secondary" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-semibold text-text-primary truncate">{s.name}</h3>
                    <Badge variant={s.provider}>{s.provider.toUpperCase()}</Badge>
                  </div>
                  <p className="text-xs text-text-muted line-clamp-2">{s.description}</p>
                  <p className="text-[10px] text-text-muted mt-2 uppercase tracking-wide">{s.category}</p>
                </div>
              </div>
            </Card>
          ) : (
            <Card key={i} hover className="px-4 py-3">
              <div className="flex items-center gap-4">
                <Icon className="w-4 h-4 text-text-muted shrink-0" />
                <span className="text-sm font-medium text-text-primary flex-1 truncate">{s.name}</span>
                <Badge variant={s.provider}>{s.provider.toUpperCase()}</Badge>
                <span className="text-xs text-text-muted hidden md:block truncate max-w-xs">{s.category}</span>
              </div>
            </Card>
          );
        })}
      </div>
      {filtered.length > 60 && (
        <p className="text-center text-sm text-text-muted">Showing 60 of {filtered.length} services</p>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// DIAGRAM TRANSLATOR
// ═══════════════════════════════════════════════════════════════
function DiagramTranslator() {
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

  // ── Upload & Analyze ──
  const handleUpload = async (file) => {
    setError(null);
    setStep('analyzing');
    setAnalyzeProgress([]);

    const zones = [
      'Connecting to analysis engine...',
      'Zone 1: Ingest (Direct Connect, IoT Greengrass, IoT Core)...',
      'Zone 2: OTA Ingest (IoT Core real-time)...',
      'Zone 3: Data Quality Check (EMR, S3 splits)...',
      'Zone 4: Orchestration (MWAA workflows)...',
      'Zone 5: Data Enrichment (Fargate, EMR, S3)...',
      'Zone 6: Scene Detection (EMR + ML)...',
      'Zone 7: Data Catalog (Glue, Neptune, DynamoDB, ES)...',
      'Zone 8: Image Anonymization (Fargate, Lambda, Rekognition)...',
      'Zone 9: Labeling (SageMaker Ground Truth)...',
      'Zone 10: Analytics & Visualization (QuickSight, AppSync)...',
      'Mapping AWS services to Azure equivalents...',
      'Calculating confidence scores...',
      'Analysis complete.',
    ];

    for (const msg of zones) {
      await new Promise(r => setTimeout(r, 250 + Math.random() * 200));
      setAnalyzeProgress(prev => [...prev, msg]);
    }

    try {
      const formData = new FormData();
      formData.append('file', file);
      const uploadRes = await fetch(`${API_BASE}/projects/demo-project/diagrams`, { method: 'POST', body: formData });
      const { diagram_id } = await uploadRes.json();
      setDiagramId(diagram_id);

      const analyzeRes = await fetch(`${API_BASE}/diagrams/${diagram_id}/analyze`, { method: 'POST' });
      const result = await analyzeRes.json();
      setAnalysis(result);

      // Fetch guided questions
      const qRes = await fetch(`${API_BASE}/diagrams/${diagram_id}/questions`, { method: 'POST' });
      const qData = await qRes.json();
      setQuestions(qData.questions || []);

      // Set defaults
      const defaults = {};
      (qData.questions || []).forEach(q => { defaults[q.id] = q.default; });
      setAnswers(defaults);

      setStep('questions');
    } catch (err) {
      setError(err.message);
      setStep('upload');
    }
  };

  // ── Apply Answers ──
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

  // ── Generate IaC ──
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

  // ── Export Diagram ──
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

  // ── Reset ──
  const reset = () => {
    setStep('upload');
    setDiagramId(null);
    setAnalysis(null);
    setQuestions([]);
    setAnswers({});
    setIacCode(null);
    setCostEstimate(null);
    setError(null);
    setAnalyzeProgress([]);
  };

  return (
    <div className="space-y-6">
      {/* Progress Steps */}
      <div className="flex items-center justify-center gap-2 text-xs font-medium">
        {[
          { id: 'upload', label: 'Upload' },
          { id: 'analyzing', label: 'Analyzing' },
          { id: 'questions', label: 'Customize' },
          { id: 'results', label: 'Results' },
          { id: 'iac', label: 'IaC Code' },
        ].map((s, i, arr) => (
          <React.Fragment key={s.id}>
            <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full transition-colors ${
              step === s.id ? 'bg-cta/15 text-cta' :
              arr.findIndex(x => x.id === step) > i ? 'text-cta' : 'text-text-muted'
            }`}>
              {arr.findIndex(x => x.id === step) > i ? <CheckCircle className="w-3.5 h-3.5" /> : <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">{i + 1}</span>}
              <span className="hidden sm:inline">{s.label}</span>
            </div>
            {i < arr.length - 1 && <ChevronRight className="w-4 h-4 text-text-muted" />}
          </React.Fragment>
        ))}
      </div>

      {error && (
        <Card className="p-4 border-danger/30">
          <div className="flex items-center gap-3">
            <XCircle className="w-5 h-5 text-danger shrink-0" />
            <p className="text-sm text-danger">{error}</p>
            <button onClick={() => setError(null)} className="ml-auto cursor-pointer"><X className="w-4 h-4 text-text-muted" /></button>
          </div>
        </Card>
      )}

      {/* ── Step: Upload ── */}
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
            <input ref={fileInputRef} type="file" accept="image/*,.pdf,.svg" onChange={e => e.target.files[0] && handleUpload(e.target.files[0])} className="hidden" />
            <Button onClick={() => fileInputRef.current?.click()} variant="primary" size="lg" icon={Upload}>
              Select Diagram File
            </Button>
            <p className="text-xs text-text-muted mt-4">Supports PNG, JPG, SVG, PDF</p>
          </div>
        </Card>
      )}

      {/* ── Step: Analyzing ── */}
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

      {/* ── Step: Questions ── */}
      {step === 'questions' && (
        <div className="space-y-6">
          <Card className="p-6">
            <div className="flex items-center gap-3 mb-2">
              <HelpCircle className="w-6 h-6 text-cta" />
              <h2 className="text-xl font-bold text-text-primary">Customize Your Azure Architecture</h2>
            </div>
            <p className="text-sm text-text-secondary">
              We detected {analysis?.services_detected || 0} AWS services across {analysis?.zones?.length || 0} zones.
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
                          <input
                            type="radio"
                            name={q.id}
                            value={opt.value}
                            checked={answers[q.id] === opt.value}
                            onChange={() => setAnswers(prev => ({ ...prev, [q.id]: opt.value }))}
                            className="w-4 h-4 accent-cta cursor-pointer"
                          />
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
                          <input
                            type="checkbox"
                            checked={(answers[q.id] || []).includes(opt.value)}
                            onChange={e => {
                              const current = answers[q.id] || [];
                              setAnswers(prev => ({
                                ...prev,
                                [q.id]: e.target.checked ? [...current, opt.value] : current.filter(v => v !== opt.value),
                              }));
                            }}
                            className="w-4 h-4 accent-cta cursor-pointer"
                          />
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

      {/* ── Step: Results ── */}
      {step === 'results' && analysis && (
        <div className="space-y-6">
          {/* Summary */}
          <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-xl font-bold text-text-primary">{analysis.diagram_type}</h2>
                <p className="text-sm text-text-secondary mt-1">
                  {analysis.services_detected} services mapped across {analysis.zones?.length} zones
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="aws">AWS</Badge>
                <ArrowRight className="w-4 h-4 text-text-muted" />
                <Badge variant="azure">Azure</Badge>
              </div>
            </div>

            {/* Confidence Dashboard */}
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
                              <span className="text-sm text-[#FF9900] font-medium">{m.source_service}</span>
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
                  <Button
                    key={f.id}
                    onClick={() => handleExportDiagram(f.id)}
                    variant="secondary"
                    size="sm"
                    loading={exportLoading[f.id]}
                    icon={Download}
                  >
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
            </div>
          </div>
        </div>
      )}

      {/* ── Step: IaC Code ── */}
      {step === 'iac' && iacCode && (
        <div className="space-y-6">
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
                  a.href = url;
                  a.download = iacFormat === 'terraform' ? 'main.tf' : 'main.bicep';
                  a.click();
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

          {/* Cost Estimate */}
          {costEstimate && (
            <Card className="p-6">
              <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-4">
                <BarChart3 className="w-5 h-5 text-cta" />
                Estimated Monthly Cost
              </h3>
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
                      <span className="text-xs font-medium text-text-primary">
                        ${s.monthly_low} - ${s.monthly_high}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          <div className="flex items-center justify-between">
            <Button onClick={() => setStep('results')} variant="ghost" icon={Eye}>Back to Results</Button>
            <Button onClick={reset} variant="secondary" icon={Upload}>New Translation</Button>
          </div>
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// CHAT WIDGET — Floating chatbot with GitHub issue creation
// ═══════════════════════════════════════════════════════════════
function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hi! I\'m the Archmorph assistant. I can help you learn about the tool or **create a GitHub issue**. What can I help you with?' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(() => `chat-${Date.now()}`);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      const data = await res.json();
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.reply,
        action: data.action,
        data: data.data,
      }]);
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, I couldn\'t connect to the server. Please try again.' }]);
    }
    setLoading(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // Simple markdown-like rendering for bold and links
  const renderContent = (text) => {
    return text.split('\n').map((line, i) => (
      <p key={i} className={i > 0 ? 'mt-1.5' : ''}>
        {line.split(/(\*\*.*?\*\*|\[.*?\]\(.*?\))/).map((part, j) => {
          const boldMatch = part.match(/^\*\*(.*?)\*\*$/);
          if (boldMatch) return <strong key={j} className="font-semibold">{boldMatch[1]}</strong>;
          const linkMatch = part.match(/^\[(.*?)\]\((.*?)\)$/);
          if (linkMatch) return <a key={j} href={linkMatch[2]} target="_blank" rel="noopener noreferrer" className="text-cta underline cursor-pointer">{linkMatch[1]}</a>;
          return part;
        })}
      </p>
    ));
  };

  return (
    <>
      {/* Toggle button */}
      <button
        onClick={() => setOpen(!open)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-cta hover:bg-cta-hover text-surface shadow-lg shadow-cta/30 flex items-center justify-center transition-all duration-200 cursor-pointer"
        aria-label="Open chat"
      >
        {open ? <X className="w-6 h-6" /> : <MessageSquare className="w-6 h-6" />}
      </button>

      {/* Chat panel */}
      {open && (
        <div className="fixed bottom-24 right-6 z-50 w-96 max-w-[calc(100vw-2rem)] bg-primary border border-border rounded-2xl shadow-2xl shadow-black/40 flex flex-col overflow-hidden animate-slide-up" style={{ height: '500px' }}>
          {/* Header */}
          <div className="px-4 py-3 bg-secondary border-b border-border flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-cta/15 flex items-center justify-center">
              <MessageSquare className="w-4 h-4 text-cta" />
            </div>
            <div className="flex-1">
              <h3 className="text-sm font-semibold text-text-primary">Archmorph Assistant</h3>
              <p className="text-[10px] text-text-muted">Ask questions or create GitHub issues</p>
            </div>
            <button onClick={() => setOpen(false)} className="p-1 hover:bg-border rounded cursor-pointer">
              <X className="w-4 h-4 text-text-muted" />
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] px-3 py-2 rounded-xl text-sm ${
                  msg.role === 'user'
                    ? 'bg-cta/15 text-text-primary rounded-br-sm'
                    : 'bg-secondary text-text-primary rounded-bl-sm'
                }`}>
                  {renderContent(msg.content)}
                  {msg.action === 'issue_created' && msg.data && (
                    <div className="mt-2 p-2 bg-cta/10 rounded-lg border border-cta/20">
                      <div className="flex items-center gap-1.5 text-xs text-cta font-medium">
                        <CheckCircle className="w-3.5 h-3.5" />
                        Issue #{msg.data.issue_number} created
                      </div>
                    </div>
                  )}
                  {msg.action === 'issue_draft' && msg.data && (
                    <div className="mt-2 p-2 bg-warning/10 rounded-lg border border-warning/20">
                      <div className="flex items-center gap-1.5 text-xs text-warning font-medium">
                        <FileText className="w-3.5 h-3.5" />
                        Draft ready — reply "yes" to create
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-secondary px-3 py-2 rounded-xl rounded-bl-sm">
                  <Loader2 className="w-4 h-4 text-text-muted animate-spin" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="px-3 py-3 border-t border-border">
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type a message..."
                className="flex-1 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 transition-colors"
              />
              <button
                onClick={sendMessage}
                disabled={!input.trim() || loading}
                className="p-2 rounded-lg bg-cta hover:bg-cta-hover text-surface disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


// ═══════════════════════════════════════════════════════════════
// ADMIN DASHBOARD — Hidden funnel analytics (admin-only)
// ═══════════════════════════════════════════════════════════════
const ADMIN_KEY = 'archmorph-admin-2025';

function AdminDashboard({ onClose }) {
  const [funnel, setFunnel] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [daily, setDaily] = useState([]);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/admin/metrics/funnel?key=${ADMIN_KEY}`).then(r => r.json()),
      fetch(`${API_BASE}/admin/metrics?key=${ADMIN_KEY}`).then(r => r.json()),
      fetch(`${API_BASE}/admin/metrics/daily?key=${ADMIN_KEY}&days=14`).then(r => r.json()),
      fetch(`${API_BASE}/admin/metrics/recent?key=${ADMIN_KEY}&limit=30`).then(r => r.json()),
    ]).then(([f, m, d, r]) => {
      setFunnel(f);
      setMetrics(m);
      setDaily(d.data || []);
      setRecent(r.events || []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="fixed inset-0 z-[100] bg-surface flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-cta animate-spin" />
    </div>
  );

  const maxFunnel = funnel?.funnel?.[0]?.count || 1;
  const maxDaily = Math.max(...daily.map(d => d.total), 1);

  const STEP_COLORS = ['#22C55E', '#3B82F6', '#A855F7', '#F59E0B', '#EF4444', '#06B6D4'];

  return (
    <div className="fixed inset-0 z-[100] bg-surface overflow-y-auto">
      {/* Admin Header */}
      <div className="sticky top-0 z-10 bg-surface/90 backdrop-blur-xl border-b border-border">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-danger/15 flex items-center justify-center">
              <Shield className="w-5 h-5 text-danger" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-text-primary">Admin Analytics</h1>
              <p className="text-[10px] text-text-muted uppercase tracking-wider">Archmorph Internal</p>
            </div>
          </div>
          <Button variant="ghost" size="sm" icon={X} onClick={onClose}>Close</Button>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-8 space-y-8">

        {/* ── Summary Row ─────────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Sessions', value: funnel?.total_sessions || 0, icon: Activity, color: 'cta' },
            { label: 'Completion Rate', value: `${funnel?.completion_rate || 0}%`, icon: TrendingUp, color: 'cta' },
            { label: 'Bottleneck', value: funnel?.bottleneck || 'None', icon: AlertTriangle, color: 'warning' },
            { label: 'Events Today', value: metrics?.today?.events || 0, icon: Zap, color: 'cta' },
          ].map(s => (
            <Card key={s.label} className="p-4">
              <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-lg bg-${s.color}/10 flex items-center justify-center`}>
                  <s.icon className={`w-5 h-5 text-${s.color}`} />
                </div>
                <div>
                  <p className="text-xl font-bold text-text-primary truncate">{s.value}</p>
                  <p className="text-xs text-text-muted">{s.label}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>

        {/* ── Conversion Funnel ───────────────────────────── */}
        <Card className="p-6">
          <h3 className="text-sm font-semibold text-text-primary mb-6 flex items-center gap-2">
            <Filter className="w-4 h-4 text-cta" />
            User Conversion Funnel
          </h3>
          <div className="space-y-3">
            {(funnel?.funnel || []).map((step, i) => {
              const pct = maxFunnel > 0 ? (step.count / maxFunnel * 100) : 0;
              return (
                <div key={step.step}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center text-surface" style={{ backgroundColor: STEP_COLORS[i] }}>
                        {i + 1}
                      </span>
                      <span className="text-sm font-medium text-text-primary">{step.label}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-bold text-text-primary">{step.count}</span>
                      {i > 0 && (
                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                          step.conversion_rate >= 70 ? 'bg-cta/15 text-cta' :
                          step.conversion_rate >= 40 ? 'bg-warning/15 text-warning' :
                          'bg-danger/15 text-danger'
                        }`}>
                          {step.conversion_rate}%
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="h-8 bg-surface rounded-lg overflow-hidden">
                    <div
                      className="h-full rounded-lg transition-all duration-500"
                      style={{ width: `${Math.max(pct, 1)}%`, backgroundColor: STEP_COLORS[i], opacity: 0.8 }}
                    />
                  </div>
                  {i > 0 && step.drop_off > 0 && (
                    <p className="text-[10px] text-text-muted mt-0.5 ml-7">
                      {step.drop_off} user{step.drop_off !== 1 ? 's' : ''} dropped off
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </Card>

        {/* ── Two-column: Daily Activity + Event Counters ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Daily Activity */}
          <Card className="p-6">
            <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-cta" />
              Daily Activity (14 Days)
            </h3>
            <div className="flex items-end gap-1 h-36">
              {daily.map(d => (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group">
                  <span className="text-[9px] text-text-muted opacity-0 group-hover:opacity-100 transition-opacity">{d.total}</span>
                  <div
                    className="w-full bg-cta/20 hover:bg-cta/40 rounded-t transition-colors"
                    style={{ height: `${Math.max((d.total / maxDaily) * 100, 3)}%` }}
                    title={`${d.date}: ${d.total} events`}
                  />
                  <span className="text-[8px] text-text-muted truncate w-full text-center">{d.date.slice(5)}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* Event Counters */}
          <Card className="p-6">
            <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
              <Activity className="w-4 h-4 text-cta" />
              All-Time Counters
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(metrics?.totals || {}).filter(([, v]) => v > 0).map(([key, val]) => (
                <div key={key} className="bg-surface rounded-lg p-2.5 flex items-center justify-between">
                  <span className="text-[11px] text-text-muted truncate">{key.replace(/_/g, ' ')}</span>
                  <span className="text-sm font-bold text-text-primary ml-2">{val}</span>
                </div>
              ))}
              {Object.values(metrics?.totals || {}).every(v => v === 0) && (
                <p className="text-sm text-text-muted col-span-2 text-center py-4">No data yet</p>
              )}
            </div>
          </Card>
        </div>

        {/* ── Recent Sessions ─────────────────────────────── */}
        <Card className="p-6">
          <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
            <Eye className="w-4 h-4 text-cta" />
            Recent Sessions
          </h3>
          {(funnel?.recent_sessions || []).length === 0 ? (
            <p className="text-sm text-text-muted text-center py-6">No sessions recorded yet</p>
          ) : (
            <div className="space-y-2 max-h-72 overflow-auto">
              {(funnel?.recent_sessions || []).map((sess, i) => (
                <div key={i} className="flex items-center gap-3 py-2.5 px-3 bg-surface rounded-lg">
                  <div className={`w-2 h-2 rounded-full shrink-0 ${sess.completed ? 'bg-cta' : 'bg-warning'}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-primary font-medium truncate">{sess.session_id}</p>
                    <p className="text-[10px] text-text-muted">
                      Reached: <span className="text-text-secondary">{sess.farthest_step}</span>
                      {' '}&middot;{' '}
                      {sess.steps_completed} step{sess.steps_completed !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    {sess.completed ? (
                      <Badge variant="high">Completed</Badge>
                    ) : (
                      <Badge variant="medium">Dropped</Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* ── Recent Events Feed ──────────────────────────── */}
        <Card className="p-6">
          <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
            <Zap className="w-4 h-4 text-cta" />
            Recent Events
          </h3>
          {recent.length === 0 ? (
            <p className="text-sm text-text-muted text-center py-4">No recent events</p>
          ) : (
            <div className="space-y-1.5 max-h-56 overflow-auto">
              {recent.map((evt, i) => (
                <div key={i} className="flex items-center gap-3 py-1.5 text-sm">
                  <span className="w-2 h-2 rounded-full bg-cta/40 shrink-0" />
                  <span className="text-text-primary flex-1 truncate">{evt.type.replace(/_/g, ' ')}</span>
                  <span className="text-xs text-text-muted shrink-0">{new Date(evt.timestamp).toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// APP
// ═══════════════════════════════════════════════════════════════
export default function App() {
  const [activeTab, setActiveTab] = useState('translator');
  const [updateStatus, setUpdateStatus] = useState(null);
  const [adminOpen, setAdminOpen] = useState(false);
  const [tapCount, setTapCount] = useState(0);
  const tapTimer = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE}/service-updates/status`)
      .then(r => r.json())
      .then(setUpdateStatus)
      .catch(() => {});
  }, []);

  // Hidden admin: click version text 5 times rapidly to open
  const handleVersionClick = () => {
    const next = tapCount + 1;
    setTapCount(next);
    clearTimeout(tapTimer.current);
    if (next >= 5) {
      setAdminOpen(true);
      setTapCount(0);
    } else {
      tapTimer.current = setTimeout(() => setTapCount(0), 2000);
    }
  };

  return (
    <div className="min-h-screen bg-surface text-text-primary font-sans">
      <Nav activeTab={activeTab} setActiveTab={setActiveTab} updateStatus={updateStatus} />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {activeTab === 'translator' && <DiagramTranslator />}
        {activeTab === 'services' && <ServicesBrowser />}
      </main>
      <footer className="border-t border-border py-8 mt-12">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <p
              className="text-xs text-text-muted select-none cursor-default"
              onClick={handleVersionClick}
            >
              Archmorph v2.1.0 — AI-powered Cloud Architecture Translator to Azure
            </p>
            <div className="flex items-center gap-4">
              <a href="mailto:send2katz@gmail.com" className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-cta transition-colors cursor-pointer">
                <Mail className="w-3.5 h-3.5" />
                send2katz@gmail.com
              </a>
              <a href="https://github.com/idokatz86/Archmorph" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-cta transition-colors cursor-pointer">
                <Code className="w-3.5 h-3.5" />
                GitHub
              </a>
            </div>
          </div>
        </div>
      </footer>
      <ChatWidget />
      {adminOpen && <AdminDashboard onClose={() => setAdminOpen(false)} />}
    </div>
  );
}
