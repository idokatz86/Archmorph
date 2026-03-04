import React, { useState } from 'react';
import {
  ArrowRight, AlertTriangle, Info, HelpCircle,
  FileCode, Sparkles, Loader2, ChevronDown, ChevronUp, ShieldCheck,
} from 'lucide-react';
import { Badge, Button, Card } from '../ui';
import ExportPanel from './ExportPanel';

/* ── Confidence Explanation Row ──────────────────────────── */
function MappingRow({ m, sourceProvider }) {
  const [open, setOpen] = useState(false);
  const hasExplanation = m.confidence_explanation?.length > 0;

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
          onClick={() => hasExplanation && setOpen(!open)}
          className={`flex items-center gap-1.5 ${hasExplanation ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}`}
          title={hasExplanation ? 'Click to see why this confidence score was assigned' : ''}
          aria-expanded={open}
        >
          <Badge variant={m.confidence >= 0.9 ? 'high' : m.confidence >= 0.8 ? 'medium' : 'low'}>
            {(m.confidence * 100).toFixed(0)}%
          </Badge>
          {hasExplanation && (
            open
              ? <ChevronUp className="w-3.5 h-3.5 text-text-muted" />
              : <ChevronDown className="w-3.5 h-3.5 text-text-muted" />
          )}
        </button>
      </div>

      {/* Confidence Explanation Panel */}
      {open && hasExplanation && (
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
