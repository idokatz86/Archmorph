import React, { useState, Suspense, lazy } from 'react';
import {
  ArrowRight, AlertTriangle, Info, HelpCircle,
  FileCode, Sparkles, Loader2, ChevronDown, ChevronUp, ShieldCheck,
  CheckCircle2, XCircle, ExternalLink, FileText, ArrowUpRight, Mail,
  Package,
} from 'lucide-react';
import { Badge, Button, Card } from '../ui';
import ExportPanel from './ExportPanel';
import ResultsTable from './ResultsTable';
import ExportHub from './ExportHub';
import { HelpTooltip, HELP_CONTENT } from '../HelpTooltip';
import { toRenderableString } from '../../utils/toRenderableString';

const ArchitectureFlow = lazy(() => import('./ArchitectureFlow'));
const DependencyGraph = lazy(() => import('./DependencyGraph'));

/* ── Strengths/Limitations Panel for a mapping ──────────── */
function DeepDivePanel({ m }) {
  const isDummy = (v) => {
    if (!v) return true;
    const s = String(v).toLowerCase().trim();
    return s === 'none' || s === 'n/a' || s === 'none.' || s === 'none identified';
  };
  const isRealItem = (item) => {
    if (!item) return false;
    if (typeof item === 'string') return !isDummy(item);
    return !(isDummy(item.factor) && isDummy(item.detail));
  };

  const strengths = (m.strengths || []).filter(isRealItem);
  const limitations = (m.limitations || []).filter(isRealItem);
  const migrationNotes = (m.migration_notes || []).filter(isRealItem);
  
  const origDataCount = (m.strengths?.length || 0) + (m.limitations?.length || 0) + (m.migration_notes?.length || 0);
  const hasData = origDataCount > 0;

  const defaultTab = strengths.length > 0 ? 'strengths' : (limitations.length > 0 ? 'limitations' : 'migration');
  const [tab, setTab] = useState(defaultTab);

  if (!hasData) return null;

  return (
    <div className="mt-2 ml-1 pl-3 border-l-2 border-info/30 space-y-2 animate-in fade-in slide-in-from-top-1">
      <div className="flex gap-1">
        {[
          { id: 'strengths', label: 'Strengths', count: strengths.length, color: 'text-cta' },
          { id: 'limitations', label: 'Limitations', count: limitations.length, color: 'text-danger' },
          { id: 'migration', label: 'Migration', count: migrationNotes.length, color: 'text-info' },
        ].filter(t => t.id === 'limitations' || t.count > 0).map(t => (
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

      {tab === 'strengths' && strengths.map((s, i) => {
        const factor = typeof s === 'string' ? s : s.factor;
        const detail = typeof s === 'string' ? null : s.detail;
        return (
          <div key={i} className="flex items-start gap-2 text-xs text-text-secondary">
            <CheckCircle2 className="w-3.5 h-3.5 text-cta shrink-0 mt-0.5" />
            <div>
              <span className="font-medium text-text-primary">{factor}</span>
              {detail && <span className="text-text-muted"> — {detail}</span>}
            </div>
          </div>
        );
      })}

      {tab === 'limitations' && (
        limitations.length > 0 ? limitations.map((l, i) => {
          const factor = typeof l === 'string' ? l : l.factor || 'Limitation';
          const detail = typeof l === 'string' ? null : l.detail;
          const severity = typeof l === 'string' ? 'medium' : l.severity;
          const doc_link = typeof l === 'string' ? null : l.doc_link;

          const severityConfig = {
            high:   { bg: 'bg-danger/10', border: 'border-danger/20', dot: 'bg-danger', text: 'text-danger', label: 'Likely blocker' },
            medium: { bg: 'bg-warning/10', border: 'border-warning/20', dot: 'bg-warning', text: 'text-warning', label: 'May need workaround' },
            low:    { bg: 'bg-text-muted/10', border: 'border-text-muted/15', dot: 'bg-text-muted', text: 'text-text-muted', label: 'Minor gap' },
          };
          const sc = severityConfig[severity] || severityConfig.medium;

          return (
            <div key={i} className={`rounded-lg p-3 ${sc.bg} border ${sc.border} space-y-1.5`}>
              {/* Layer 1: Headline + Impact pill */}
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 min-w-0">
                  <AlertTriangle className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${sc.text}`} />
                  <span className="text-xs font-semibold text-text-primary leading-snug">{factor}</span>
                </div>
                <span className={`inline-flex items-center gap-1.5 text-[10px] font-medium ${sc.text} shrink-0`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${sc.dot}`} />
                  {sc.label}
                </span>
              </div>

              {/* Layer 2: Detail summary */}
              {detail && (
                <p className="text-[11px] text-text-muted leading-relaxed ml-[22px]">
                  {detail.length > 180 ? detail.slice(0, 177) + '...' : detail}
                </p>
              )}

              {/* Layer 3: Doc CTA */}
              {doc_link && (
                <a
                  href={doc_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 ml-[22px] text-[10px] font-medium text-cta hover:text-cta/80 transition-colors group"
                >
                  <FileText className="w-3 h-3" />
                  Compare feature parity
                  <ArrowUpRight className="w-2.5 h-2.5 opacity-60 group-hover:opacity-100 transition-opacity" />
                </a>
              )}
            </div>
          );
        }) : (
          <div className="flex items-start gap-2 text-xs text-text-secondary">
            <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0 mt-0.5" />
            <p className="font-medium text-success">No known architectural limitations. This is a clean mapping.</p>
          </div>
        )
      )}

      {tab === 'migration' && migrationNotes.map((n, i) => {
        const area = typeof n === 'string' ? 'General' : n.area || 'General';
        const note = typeof n === 'string' ? n : n.note;
        const effort = typeof n === 'string' ? 'unknown' : n.effort || 'unknown';
        const doc_link = typeof n === 'string' ? null : n.doc_link;
        return (
        <div key={i} className="flex items-start gap-2 text-xs text-text-secondary">
          <ArrowRight className="w-3.5 h-3.5 text-info shrink-0 mt-0.5" />
          <div>
            <Badge variant="azure" className="text-[9px] mr-1.5">{area}</Badge>
            <span className="text-text-muted">{note}</span>
            <Badge variant={effort === 'high' ? 'low' : effort === 'low' ? 'high' : 'medium'} className="ml-1.5 text-[9px]">
              {effort} effort
            </Badge>
            {doc_link && (
              <a href={doc_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[10px] text-cta hover:underline mt-0.5 block">
                <ExternalLink className="w-2.5 h-2.5" /> Reference Guide
              </a>
            )}
          </div>
        </div>
      )})}
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
            <span className={`text-sm font-medium ${sourceProvider === 'gcp' ? 'text-[#EA4335]' : 'text-[#FF9900]'}`}>{typeof m.source_service === 'object' ? m.source_service.name : m.source_service}</span>
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
  copyFeedback, genProgress, notifyEmail, onNotifyEmail,
  onSetStep, onGenerateIac, onExportDiagram, onCopyWithFeedback,
  diagramId, exportCapability, onExportCapability,
  assumptions = [], questionsCount = 0, onReviewAssumptions,
}) {
  const [resultsView, setResultsView] = useState('card');

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

      {assumptions.length > 0 && (
        <Card className="p-4 border-info/20 bg-info/5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <HelpCircle className="w-4 h-4 text-info shrink-0" />
                <h3 className="text-sm font-semibold text-text-primary">Architecture Assumptions</h3>
                <Badge variant="outline">{questionsCount} follow-up{questionsCount === 1 ? '' : 's'}</Badge>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {assumptions.slice(0, 4).map(a => (
                  <div key={a.id} className="rounded-lg border border-border/50 bg-surface/60 px-3 py-2">
                    <p className="text-xs font-medium text-text-primary truncate" title={a.question}>{a.question}</p>
                    <p className="text-xs text-text-muted mt-0.5 truncate" title={String(a.assumed_answer ?? '')}>{String(a.assumed_answer ?? 'Not specified')}</p>
                  </div>
                ))}
              </div>
              {assumptions.length > 4 && (
                <p className="text-xs text-text-muted mt-2">{assumptions.length - 4} more assumption{assumptions.length - 4 === 1 ? '' : 's'} available for review.</p>
              )}
            </div>
            <Button onClick={onReviewAssumptions || (() => onSetStep('questions'))} variant="secondary" icon={HelpCircle}>
              Review assumptions
            </Button>
          </div>
        </Card>
      )}

      {/* Results Table / Matrix / Map toggle */}
      {analysis.mappings?.length > 0 && (
        <ResultsTable
          analysis={analysis}
          activeView={resultsView}
          onViewChange={setResultsView}
        />
      )}

      {/* Map view — existing ArchitectureFlow */}
      {resultsView === 'map' && (
        <>
          <div className="mt-4">
            <Suspense fallback={<div className="h-64 flex items-center justify-center text-text-muted"><Loader2 className="w-5 h-5 animate-spin" /></div>}>
              <ArchitectureFlow analysis={analysis} />
            </Suspense>
          </div>
          {analysis.service_connections?.length > 0 && (
            <div className="mt-8">
              <h3 className="text-xl font-bold text-text-primary mb-4">Service Dependency Graph</h3>
              <Suspense fallback={<div className="h-64 flex items-center justify-center text-text-muted"><Loader2 className="w-5 h-5 animate-spin" /></div>}>
                <DependencyGraph analysis={analysis} />
              </Suspense>
            </div>
          )}
        </>
      )}

      {/* Zone detail — show only in map view for legacy compatibility */}
      {resultsView === 'map' && (
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
      )}

      {/* Warnings */}
      {analysis.warnings?.length > 0 && (
        <Card className="p-4">
          <h3 className="text-sm font-semibold text-warning flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4" />
            Warnings and Recommendations
          </h3>
          <div className="space-y-2">
            {analysis.warnings.map((w, i) => {
              // Backend GPT vision prompt asks for `{type, message}` objects;
              // older / partial responses can also return plain strings. Coerce
              // to text so we never render a raw object (would trigger React #31).
              const text = toRenderableString(w);
              if (!text) return null;
              return (
                <div key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                  <Info className="w-3.5 h-3.5 text-warning shrink-0 mt-0.5" />
                  <span>{text}</span>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Export Diagram + Export Hub */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
        <div className="flex-1">
          <ExportPanel exportLoading={exportLoading} onExportDiagram={onExportDiagram} />
        </div>
        <Button onClick={() => document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'export-hub' }))} variant="secondary" icon={Package}>
          Export All
        </Button>
      </div>

      {/* Export Hub Modal */}
      <ExportHub
        diagramId={diagramId}
        exportCapability={exportCapability}
        onExportCapability={onExportCapability}
      />

      {/* Generation Progress Indicator (#311) */}
      {generatingIac && (
        <Card className="p-4 border-cta/30 bg-cta/5 space-y-3" role="status" aria-live="polite">
          <div className="flex items-center gap-3">
            <Loader2 className="w-5 h-5 text-cta animate-spin shrink-0" aria-hidden="true" />
            <div>
              <p className="text-sm text-text-primary font-medium">
                {genProgress || `Generating ${iacFormat === 'terraform' ? 'Terraform' : iacFormat === 'bicep' ? 'Bicep' : iacFormat === 'pulumi' ? 'Pulumi' : iacFormat === 'aws-cdk' ? 'AWS CDK' : 'CloudFormation'} code...`}
              </p>
              {genProgress && <p className="text-xs text-text-muted mt-0.5">Generating IaC + HLD together to save you time</p>}
            </div>
          </div>
          {/* Email notification opt-in */}
          {!notifyEmail?.sent && (
            <div className="flex items-center gap-2 ml-8">
              <Mail className="w-3.5 h-3.5 text-text-muted shrink-0" />
              <input
                type="email"
                placeholder="Get notified when ready (email)"
                className="flex-1 text-xs px-2.5 py-1.5 rounded-md bg-surface border border-border text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-cta"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && e.target.value.includes('@')) {
                    onNotifyEmail?.(e.target.value);
                  }
                }}
              />
              <button
                onClick={(e) => {
                  const input = e.target.closest('div')?.querySelector('input');
                  if (input?.value?.includes('@')) onNotifyEmail?.(input.value);
                }}
                className="text-[10px] px-2.5 py-1.5 rounded-md bg-cta/15 text-cta font-medium hover:bg-cta/25 transition-colors"
              >
                Notify me
              </button>
            </div>
          )}
          {notifyEmail?.sent && !notifyEmail?.failed && (
            <div className="flex items-center gap-2 ml-8 text-xs bg-cta/10 border border-cta/20 rounded-md px-3 py-2 text-cta animate-in fade-in">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>Email accepted! We'll notify <strong>{notifyEmail.email}</strong> when your outputs are ready.</span>
            </div>
          )}
          {notifyEmail?.failed && (
            <div className="flex items-center gap-2 ml-8 text-xs bg-warning/10 border border-warning/20 rounded-md px-3 py-2 text-warning animate-in fade-in">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>Could not register email — but don't worry, your outputs will still appear here when ready.</span>
            </div>
          )}
        </Card>
      )}

      {/* Generate Buttons — responsive wrap for mobile (#306) */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <Button onClick={() => onSetStep('questions')} variant="ghost" icon={HelpCircle}>Back to Questions</Button>
        <div className="flex flex-wrap items-center gap-2 justify-end">
          <Button onClick={() => onGenerateIac('terraform')} loading={loading && iacFormat === 'terraform'} icon={FileCode}>Terraform</Button>
          <Button onClick={() => onGenerateIac('bicep')} variant="secondary" loading={loading && iacFormat === 'bicep'} icon={FileCode}>Bicep</Button>
          <Button onClick={() => onGenerateIac('cloudformation')} variant="secondary" loading={loading && iacFormat === 'cloudformation'} icon={FileCode}>CloudFormation</Button>
          <Button onClick={() => onGenerateIac('pulumi')} variant="secondary" loading={loading && iacFormat === 'pulumi'} icon={FileCode}>Pulumi</Button>
          <Button onClick={() => onGenerateIac('aws-cdk')} variant="secondary" loading={loading && iacFormat === 'aws-cdk'} icon={FileCode}>AWS CDK</Button>
        </div>
      </div>
    </div>
  );
}
