import React, { useState, useEffect, useCallback } from 'react';
import {
  X, Download, Check, Loader2, Package, FileCode,
  FileText, DollarSign, CalendarClock, FileDown,
  ChevronDown, PanelTop,
} from 'lucide-react';
import { Button, Card } from '../ui';
import api from '../../services/apiClient';
import { loadCachedImage } from '../../services/sessionCache';
import useFocusTrap from '../../hooks/useFocusTrap';
import LandingZoneViewer from './LandingZoneViewer';

const DELIVERABLES = [
  {
    id: 'iac',
    label: 'Infrastructure Code',
    icon: FileCode,
    formats: [
      { id: 'terraform', label: 'Terraform' },
      { id: 'bicep', label: 'Bicep' },
    ],
    defaultFormat: 'terraform',
  },
  {
    id: 'architecture-package',
    label: 'Architecture Package',
    icon: PanelTop,
    formats: [
      { id: 'html', label: 'HTML' },
      { id: 'svg-primary', label: 'Target SVG' },
      { id: 'svg-dr', label: 'DR SVG' },
    ],
    defaultFormat: 'html',
  },
  {
    id: 'hld',
    label: 'High-Level Design',
    icon: FileText,
    formats: [
      { id: 'docx', label: 'DOCX' },
      { id: 'pdf', label: 'PDF' },
      { id: 'pptx', label: 'PPTX' },
    ],
    defaultFormat: 'docx',
  },
  {
    id: 'cost',
    label: 'Cost Estimate',
    icon: DollarSign,
    formats: [
      { id: 'csv', label: 'CSV' },
      { id: 'pdf', label: 'PDF' },
    ],
    defaultFormat: 'csv',
  },
  {
    id: 'timeline',
    label: 'Migration Timeline',
    icon: CalendarClock,
    formats: [
      { id: 'json', label: 'JSON' },
      { id: 'markdown', label: 'Markdown' },
      { id: 'csv', label: 'CSV' },
    ],
    defaultFormat: 'markdown',
  },
  {
    id: 'pdf-report',
    label: 'PDF Analysis Report',
    icon: FileDown,
    formats: null, // checkbox only
    defaultFormat: null,
  },
];

// Generate a deliverable blob via the appropriate API
async function generateDeliverable(diagramId, deliverable, format, hldIncludeDiagrams, exportCapability) {
  const id = deliverable.id;

  if (id === 'iac') {
    const data = await api.post(`/diagrams/${diagramId}/generate?format=${format}`, undefined, undefined, 180_000);
    const content = data.code || JSON.stringify(data, null, 2);
    const ext = format === 'terraform' ? 'tf' : format === 'bicep' ? 'bicep' : format;
    return { blob: new Blob([content], { type: 'text/plain' }), filename: `archmorph-iac.${ext}` };
  }

  if (id === 'architecture-package') {
    const packageFormat = format.startsWith('svg') ? 'svg' : format;
    const packageDiagram = format === 'svg-dr' ? '&diagram=dr' : '';
    const data = await api.post(
      `/diagrams/${diagramId}/export-architecture-package?format=${packageFormat}${packageDiagram}`,
      undefined,
      undefined,
      undefined,
      exportCapability ? { 'X-Export-Capability': exportCapability } : {},
    );
    const content = typeof data.content === 'string' ? data.content : JSON.stringify(data.content, null, 2);
    const mime = packageFormat === 'html' ? 'text/html' : 'image/svg+xml';
    const filename = data.filename || `archmorph-architecture-package${format === 'svg-dr' ? '-dr' : ''}.${packageFormat}`;
    return {
      blob: new Blob([content], { type: mime }),
      filename,
      exportCapability: data.export_capability || null,
      svgContent: packageFormat === 'svg' ? content : null,
      svgVariant: format === 'svg-dr' ? 'dr' : 'primary',
    };
  }

  if (id === 'hld') {
    const cachedImg = loadCachedImage(diagramId);
    const exportBody = cachedImg?.base64 ? { diagram_image: cachedImg.base64 } : {};
    const data = await api.post(
      `/diagrams/${diagramId}/export-hld?format=${format}&include_diagrams=${hldIncludeDiagrams}&export_mode=customer`,
      exportBody,
      undefined,
      undefined,
      exportCapability ? { 'X-Export-Capability': exportCapability } : {},
    );
    const bytes = Uint8Array.from(atob(data.content_b64), c => c.charCodeAt(0));
    return { blob: new Blob([bytes], { type: data.content_type }), filename: data.filename, exportCapability: data.export_capability || null };
  }

  if (id === 'cost') {
    if (format === 'csv') {
      const data = await api.get(`/diagrams/${diagramId}/cost-estimate`);
      const rows = [['Service', 'Monthly Low ($)', 'Monthly High ($)']];
      (data.services || []).forEach(s => rows.push([s.service, s.monthly_low, s.monthly_high]));
      rows.push(['Total', data.total_monthly_estimate?.low, data.total_monthly_estimate?.high]);
      const csv = rows.map(r => r.join(',')).join('\n');
      return { blob: new Blob([csv], { type: 'text/csv' }), filename: 'archmorph-cost-estimate.csv' };
    }
    // PDF cost — use export-hld with cost-only section as fallback
    const data = await api.get(`/diagrams/${diagramId}/cost-estimate`);
    const md = `# Cost Estimate\n\n| Service | Low ($/mo) | High ($/mo) |\n|---|---|---|\n${
      (data.services || []).map(s => `| ${s.service} | ${s.monthly_low} | ${s.monthly_high} |`).join('\n')
    }\n\n**Total:** $${data.total_monthly_estimate?.low} – $${data.total_monthly_estimate?.high}/mo`;
    return { blob: new Blob([md], { type: 'text/markdown' }), filename: 'archmorph-cost-estimate.md' };
  }

  if (id === 'timeline') {
    const data = await api.get(`/diagrams/${diagramId}/cost-estimate`);
    const timeline = {
      generated: new Date().toISOString(),
      phases: [
        { phase: 'Assessment', duration: '1-2 weeks', services: (data.services || []).slice(0, 3).map(s => s.service) },
        { phase: 'Migration', duration: '4-8 weeks', services: (data.services || []).map(s => s.service) },
        { phase: 'Validation', duration: '1-2 weeks', services: [] },
      ],
    };
    if (format === 'json') {
      return { blob: new Blob([JSON.stringify(timeline, null, 2)], { type: 'application/json' }), filename: 'archmorph-timeline.json' };
    }
    if (format === 'csv') {
      const rows = [['Phase', 'Duration', 'Services']];
      timeline.phases.forEach(p => rows.push([p.phase, p.duration, p.services.join('; ')]));
      return { blob: new Blob([rows.map(r => r.join(',')).join('\n')], { type: 'text/csv' }), filename: 'archmorph-timeline.csv' };
    }
    // markdown
    const md = `# Migration Timeline\n\n${timeline.phases.map(p => `## ${p.phase}\n- **Duration:** ${p.duration}\n- **Services:** ${p.services.join(', ') || 'All'}`).join('\n\n')}`;
    return { blob: new Blob([md], { type: 'text/markdown' }), filename: 'archmorph-timeline.md' };
  }

  if (id === 'pdf-report') {
    const data = await api.post(
      `/diagrams/${diagramId}/export-hld?format=pdf&include_diagrams=true&export_mode=customer`,
      {},
      undefined,
      undefined,
      exportCapability ? { 'X-Export-Capability': exportCapability } : {},
    );
    const bytes = Uint8Array.from(atob(data.content_b64), c => c.charCodeAt(0));
    return { blob: new Blob([bytes], { type: 'application/pdf' }), filename: data.filename || 'archmorph-report.pdf', exportCapability: data.export_capability || null };
  }

  throw new Error(`Unknown deliverable: ${id}`);
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ExportHub({ diagramId, hldIncludeDiagrams = true, exportCapability = null, onExportCapability }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(() => {
    const init = {};
    DELIVERABLES.forEach(d => { init[d.id] = true; });
    return init;
  });
  const [formats, setFormats] = useState(() => {
    const init = {};
    DELIVERABLES.forEach(d => { if (d.defaultFormat) init[d.id] = d.defaultFormat; });
    return init;
  });
  // 'idle' | 'loading' | 'done' | 'error'
  const [itemStatus, setItemStatus] = useState({});
  const [results, setResults] = useState({});
  const [generating, setGenerating] = useState(false);
  const modalRef = useFocusTrap(open);

  // Keyboard: Cmd+E to open
  useEffect(() => {
    const handleKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'e') {
        e.preventDefault();
        setOpen(prev => !prev);
      }
    };
    const handleCommand = (e) => {
      if (e.detail === 'export-hub') setOpen(true);
    };
    document.addEventListener('keydown', handleKey);
    document.addEventListener('archmorph:command', handleCommand);
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.removeEventListener('archmorph:command', handleCommand);
    };
  }, []);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleEsc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, [open]);

  // Click outside
  const handleBackdropClick = useCallback((e) => {
    if (e.target === e.currentTarget) setOpen(false);
  }, []);

  const toggleItem = (id) => setSelected(prev => ({ ...prev, [id]: !prev[id] }));
  const setFormat = (id, fmt) => setFormats(prev => ({ ...prev, [id]: fmt }));

  const selectedItems = DELIVERABLES.filter(d => selected[d.id]);

  const handleGenerateAll = async () => {
    if (!diagramId || selectedItems.length === 0) return;
    setGenerating(true);
    selectedItems.forEach(d => setItemStatus(prev => ({ ...prev, [d.id]: 'loading' })));
    setResults({});

    // Deliverables that consume/produce one-time export-capability tokens must run
    // sequentially so each call receives the latest token from the previous response.
    // All other deliverables are independent and can run in parallel.
    const CAPABILITY_IDS = new Set(['architecture-package', 'hld', 'pdf-report']);
    const freeItems = selectedItems.filter(d => !CAPABILITY_IDS.has(d.id));
    const capItems  = selectedItems.filter(d =>  CAPABILITY_IDS.has(d.id));

    // Run up to CONCURRENCY independent deliverables at the same time.
    const CONCURRENCY = 3;
    const runFree = async () => {
      for (let i = 0; i < freeItems.length; i += CONCURRENCY) {
        const batch = freeItems.slice(i, i + CONCURRENCY);
        await Promise.allSettled(
          batch.map(async (d) => {
            try {
              const result = await generateDeliverable(diagramId, d, formats[d.id], hldIncludeDiagrams, null);
              setResults(prev => ({ ...prev, [d.id]: result }));
              setItemStatus(prev => ({ ...prev, [d.id]: 'done' }));
            } catch {
              setItemStatus(prev => ({ ...prev, [d.id]: 'error' }));
            }
          })
        );
      }
    };

    // Capability-gated deliverables run sequentially, chaining the token.
    let currentExportCapability = exportCapability;
    const runCap = async () => {
      for (const d of capItems) {
        try {
          const result = await generateDeliverable(diagramId, d, formats[d.id], hldIncludeDiagrams, currentExportCapability);
          if (result.exportCapability) {
            currentExportCapability = result.exportCapability;
            if (onExportCapability) onExportCapability(result.exportCapability);
          }
          setResults(prev => ({ ...prev, [d.id]: result }));
          setItemStatus(prev => ({ ...prev, [d.id]: 'done' }));
        } catch {
          setItemStatus(prev => ({ ...prev, [d.id]: 'error' }));
        }
      }
    };

    await Promise.all([runFree(), runCap()]);
    setGenerating(false);
  };

  const handleDownloadAll = () => {
    // Download each completed item individually
    Object.entries(results).forEach(([, result]) => {
      if (result?.blob) downloadBlob(result.blob, result.filename);
    });
  };

  const doneCount = Object.values(itemStatus).filter(s => s === 'done').length;
  const hasResults = doneCount > 0;
  const statusMessage = generating
    ? `Generating ${selectedItems.length} selected deliverables`
    : hasResults
      ? `${doneCount} deliverable${doneCount === 1 ? '' : 's'} ready`
      : `${selectedItems.length} of ${DELIVERABLES.length} deliverables selected`;
  const svgPreview = results['architecture-package']?.svgContent ? results['architecture-package'] : null;

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="export-hub-title"
    >
      <div
        ref={modalRef}
        className="bg-primary border border-border rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-hidden flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <Package className="w-5 h-5 text-cta" />
            <div>
              <h2 id="export-hub-title" className="text-lg font-bold text-text-primary">Generate Deliverables</h2>
              <p className="text-xs text-text-muted">Select outputs and formats, then generate all at once</p>
            </div>
          </div>
          <button
            onClick={() => setOpen(false)}
            className="p-1.5 rounded-lg hover:bg-secondary transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-cta/50"
            aria-label="Close"
          >
            <X className="w-5 h-5 text-text-muted" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-2">
          {DELIVERABLES.map(d => {
            const Icon = d.icon;
            const status = itemStatus[d.id];
            const checkboxId = `export-hub-${d.id}`;
            return (
              <div
                key={d.id}
                className={`flex items-center justify-between gap-4 p-3 rounded-xl border transition-colors ${
                  selected[d.id] ? 'border-cta/30 bg-cta/5' : 'border-border bg-surface'
                }`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <input
                    id={checkboxId}
                    type="checkbox"
                    checked={selected[d.id]}
                    onChange={() => toggleItem(d.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        toggleItem(d.id);
                      }
                    }}
                    className="accent-cta w-4 h-4 shrink-0 cursor-pointer focus:outline-none focus:ring-2 focus:ring-cta/50 focus:ring-offset-2 focus:ring-offset-primary rounded-sm"
                    aria-label={`Include ${d.label}`}
                  />
                  <label htmlFor={checkboxId} className="flex items-center gap-3 min-w-0 cursor-pointer">
                    <Icon className={`w-4 h-4 shrink-0 ${selected[d.id] ? 'text-cta' : 'text-text-muted'}`} aria-hidden="true" />
                    <span className={`text-sm font-medium ${selected[d.id] ? 'text-text-primary' : 'text-text-muted'}`}>{d.label}</span>
                  </label>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {/* Format selector */}
                  {d.formats && selected[d.id] && (
                    <div className="relative">
                      <select
                        value={formats[d.id] || d.defaultFormat}
                        onChange={(e) => setFormat(d.id, e.target.value)}
                        className="appearance-none text-xs px-2.5 py-1.5 pr-7 rounded-lg bg-secondary border border-border text-text-primary cursor-pointer focus:outline-none focus:ring-1 focus:ring-cta"
                        aria-label={`${d.label} format`}
                      >
                        {d.formats.map(f => (
                          <option key={f.id} value={f.id}>{f.label}</option>
                        ))}
                      </select>
                      <ChevronDown className="w-3 h-3 text-text-muted absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
                    </div>
                  )}

                  {/* Status indicator */}
                  {status === 'loading' && <Loader2 className="w-4 h-4 text-cta animate-spin" />}
                  {status === 'done' && <Check className="w-4 h-4 text-cta" />}
                  {status === 'error' && <X className="w-4 h-4 text-danger" />}

                  {/* Individual download */}
                  {status === 'done' && results[d.id] && (
                    <button
                      onClick={() => downloadBlob(results[d.id].blob, results[d.id].filename)}
                      className="p-1 rounded hover:bg-secondary transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-cta/50"
                      aria-label={`Download ${d.label}`}
                      title={`Download ${results[d.id].filename}`}
                    >
                      <Download className="w-3.5 h-3.5 text-cta" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {svgPreview && (
            <LandingZoneViewer
              svgContent={svgPreview.svgContent}
              variant={svgPreview.svgVariant}
              filename={svgPreview.filename}
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border bg-surface/50">
          <p className="text-xs text-text-muted" role="status" aria-live="polite">
            <span className="sr-only">{statusMessage}. </span>
            {selectedItems.length} of {DELIVERABLES.length} selected
            {hasResults && ` · ${doneCount} ready`}
          </p>
          <div className="flex items-center gap-2">
            {hasResults && (
              <Button onClick={handleDownloadAll} variant="secondary" size="sm" icon={Download}>
                Download All ({doneCount})
              </Button>
            )}
            <Button
              onClick={handleGenerateAll}
              loading={generating}
              disabled={selectedItems.length === 0 || !diagramId}
              icon={Package}
              size="sm"
            >
              Generate All Selected
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
