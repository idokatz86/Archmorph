import React, { useState } from 'react';
import {
  ArrowRight, AlertTriangle, Info, HelpCircle,
  FileCode, Sparkles, Loader2, ChevronDown, ChevronUp, ShieldCheck,
  CheckCircle2, XCircle, ExternalLink,
} from 'lucide-react';
import { Badge, Button, Card } from '../ui';
import ExportPanel from './ExportPanel';
import { HelpTooltip, HELP_CONTENT } from '../HelpTooltip';
import BeforeAfterView from './BeforeAfterView';

/* ── Strengths/Limitations Panel for a mapping ──────────── */
function DeepDivePanel({ m }) {
  const [tab, setTab] = useState('strengths');
  const strengths = m.strengths || [];
  const limitations = m.limitations || [];
  const migrationNotes = m.migration_notes || [];
  const hasData = strengths.length > 0 || limitations.length > 0 || migrationNotes.length > 0;

  if (!hasData) return null;

  return (
    <div className="mt-2 ml-1 pl-3 border-l-2 border-info/30 space-y-2 animate-in fade-in slide-in-from-top-1">
      <div className="flex gap-1">
        {[
          { id: 'strengths', label: 'Strengths', count: strengths.length, color: 'text-cta' },
          { id: 'limitations', label: 'Limitations', count: limitations.length, color: 'text-danger' },
          { id: 'migration', label: 'Migration', count: migrationNotes.length, color: 'text-info' },
        ].filter(t => t.count > 0).map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`text-[10px] px-2 py-0.5 rounded-full cursor-pointer transition-colors ${
              tab === t.id ? 'bg-cta/15 text-cta font-semibold' : 'text-text-muted hover:text-text-secondary'
            }`}
          >
            {t.label} ({t.count})
          </button>
        ))}
      </div>

      {tab === 'strengths' && strengths.map((s, i) => (
        <div key={i} className="flex items-start gap-2 text-xs text-text-secondary">
          <CheckCircle2 className="w-3.5 h-3.5 text-cta shrink-0 mt-0.5" />
          <div>
            <span className="font-medium text-text-primary">{s.factor}</span>
            <span className="text-text-muted"> — {s.detail}</span>
          </div>
        </div>
      ))}

      {tab === 'limitations' && limitations.map((l, i) => (
        <div key={i} className="flex items-start gap-2 text-xs text-text-secondary">
          <XCircle className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${
            l.severity === 'high' ? 'text-danger' : l.severity === 'medium' ? 'text-warning' : 'text-text-muted'
          }`} />
          <div>
            <span className="font-medium text-text-primary">{l.factor}</span>
            <Badge variant={l.severity === 'high' ? 'low' : l.severity === 'medium' ? 'medium' : 'high'} className="ml-1.5 text-[9px]">
              {l.severity}
            </Badge>
            <p className="text-text-muted mt-0.5">{l.detail}</p>
            {l.doc_link && (
              <a href={l.doc_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[10px] text-cta hover:underline mt-0.5">
                <ExternalLink className="w-2.5 h-2.5" /> Learn more
              </a>
            )}
          </div>
        </div>
      ))}

      {tab === 'migration' && migrationNotes.map((n, i) => (
        <div key={i} className="flex items-start gap-2 text-xs text-text-secondary">
          <ArrowRight className="w-3.5 h-3.5 text-info shrink-0 mt-0.5" />
          <div>
            <Badge variant="azure" className="text-[9px] mr-1.5">{n.area}</Badge>
            <span className="text-text-muted">{n.note}</span>
            <Badge variant={n.effort === 'high' ? 'low' : n.effort === 'low' ? 'high' : 'medium'} className="ml-1.5 text-[9px]">
              {n.effort} effort
            </Badge>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Confidence Explanation Row ──────────────────────────── */
function MappingRow({ m, sourceProvider }) {
  const [open, setOpen] = useState(false);
  const hasExplanation = m.confidence_explanation?.length > 0;
  const hasDeepDive = (m.strengths?.length > 0 || m.limitations?.length > 0 || m.migration_notes?.length > 0);
  const expandable = hasExplanation || hasDeepDive;

  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-sm font-medium ${sourceProvider === 'gcp' ? 'text-[#EA4335]' : 'text-[#FF9900]'}`}>{m.source_service}</span>
            <ArrowRight className="w-3.5 h-3.5 text-text-muted shrink-0" />
            <span className="text-sm text-info font-medium">{m.azure_service}</span>
          </div>
        </div>
        <button
          onClick={() => expandable && setOpen(!open)}
          className={`flex items-center gap-1.5 ${expandable ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}`}
          title={expandable ? 'Click to see confidence breakdown, strengths & limitations' : ''}
          aria-expanded={open}
        >
          <Badge variant={m.confidence >= 0.9 ? 'high' : m.confidence >= 0.8 ? 'medium' : 'low'}>
            {(m.confidence * 100).toFixed(0)}%
          </Badge>
          {expandable && (
            open
              ? <ChevronUp className="w-3.5 h-3.5 text-text-muted" />
              : <ChevronDown className="w-3.5 h-3.5 text-text-muted" />
          )}
        </button>
      </div>

      {/* Expanded: Confidence Explanation + Deep Dive */}
      {open && (
        <>
          {hasExplanation && (
            <div className="mt-2.5 ml-1 pl-3 border-l-2 border-cta/30 space-y-1.5 animate-in fade-in slide-in-from-top-1">
              <p className="text-xs font-semibold text-text-secondary flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-cta" />
                Why this confidence score?
              </p>
              {m.confidence_explanation.map((reason, idx) => (
                <div key={idx} className="flex items-start gap-2 text-xs text-text-muted">
                  <span className="text-cta/60 mt-0.5 shrink-0">•</span>
                  <span>{reason}</span>
                </div>
              ))}
            </div>
          )}
          <DeepDivePanel m={m} />
        </>
      )}
    </div>
  );
}

export default function AnalysisResults({
  analysis, loading, generatingIac, iacFormat, exportLoading,
  copyFeedback,
  onSetStep, onGenerateIac, onExportDiagram, onCopyWithFeedback,
}) {
  return (
    <div className="space-y-6">
      {/* Analysis Summary */}
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
            <Badge variant={analysis.target_provider || 'azure'}>{(analysis.target_provider || 'azure').toUpperCase()}</Badge>
          </div>
        </div>

        {analysis.confidence_summary && (
          <>
            <div className="flex items-center gap-2 mt-4 mb-2">
              <h3 className="text-sm font-semibold text-text-secondary">Confidence Summary</h3>
              <HelpTooltip {...HELP_CONTENT.confidence} />
            </div>
            <div className="grid grid-cols-4 gap-3">
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

            {/* Confidence Methodology — Transparency Panel */}
            {analysis.confidence_summary.methodology && (
              <div className="mt-3 px-3.5 py-2.5 rounded-lg bg-info/5 border border-info/20">
                <div className="flex items-start gap-2">
                  <ShieldCheck className="w-4 h-4 text-info shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs font-semibold text-info mb-1">How we calculate confidence</p>
                    <p className="text-xs text-text-secondary leading-relaxed">
                      {analysis.confidence_summary.methodology}
                    </p>
                    <p className="text-xs text-text-muted mt-1.5 italic">
                      Click any mapping's confidence badge below to see the detailed breakdown for that specific service.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </>
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
                    <MappingRow key={i} m={m} sourceProvider={analysis.source_provider} />
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

      {/* Export Diagram */}
      <ExportPanel exportLoading={exportLoading} onExportDiagram={onExportDiagram} />

      {/* Before/After Architecture Visualization (#250) */}
      <BeforeAfterView analysis={analysis} />

      {/* Generation Progress Indicator (#311) */}
      {generatingIac && (
        <Card className="p-4 border-cta/30 bg-cta/5" role="status" aria-live="polite">
          <div className="flex items-center gap-3">
            <Loader2 className="w-5 h-5 text-cta animate-spin shrink-0" aria-hidden="true" />
            <p className="text-sm text-text-primary font-medium">
              {`Generating ${iacFormat === 'terraform' ? 'Terraform' : iacFormat === 'bicep' ? 'Bicep' : 'CloudFormation'} code...`}
            </p>
          </div>
        </Card>
      )}

      {/* Generate Buttons — responsive wrap for mobile (#306) */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <Button onClick={() => onSetStep('questions')} variant="ghost" icon={HelpCircle}>Back to Questions</Button>
        <div className="flex flex-wrap items-center gap-2 justify-end">
          <Button onClick={() => onGenerateIac('terraform')} loading={loading && iacFormat === 'terraform'} icon={FileCode}>Generate Terraform</Button>
          <Button onClick={() => onGenerateIac('bicep')} variant="secondary" loading={loading && iacFormat === 'bicep'} icon={FileCode}>Generate Bicep</Button>
          <Button onClick={() => onGenerateIac('cloudformation')} variant="secondary" loading={loading && iacFormat === 'cloudformation'} icon={FileCode}>CloudFormation</Button>
        </div>
      </div>
    </div>
  );
}
