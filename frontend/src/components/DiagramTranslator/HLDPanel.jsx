import React from 'react';
import {
  Sparkles, Download, Check, FileText, Eye, Layers,
  Network, Shield, ArrowRight, Wrench,
} from 'lucide-react';
import { Button, Card } from '../ui';

const HLD_TABS = [
  { id: 'overview', label: 'Overview', icon: Eye },
  { id: 'services', label: 'Services', icon: Layers },
  { id: 'networking', label: 'Networking', icon: Network },
  { id: 'security', label: 'Security', icon: Shield },
  // FinOps tab hidden during beta — no money-related UI
  // { id: 'finops', label: 'FinOps', icon: DollarSign },
  { id: 'migration', label: 'Migration', icon: ArrowRight },
  { id: 'waf', label: 'WAF', icon: Wrench },
];

const DOC_EXPORT_FORMATS = [
  { id: 'docx', label: 'Word' },
  { id: 'pdf', label: 'PDF' },
  { id: 'pptx', label: 'PowerPoint' },
];

export default function HLDPanel({
  hldData, hldTab, hldExportLoading, hldIncludeDiagrams, copyFeedback,
  onSetHldTab, onSetHldIncludeDiagrams, onHldExport, onCopyWithFeedback,
}) {
  if (!hldData) return null;

  return (
    <Card className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <Sparkles className="w-6 h-6 text-cta" />
          <div>
            <h2 className="text-xl font-bold text-text-primary">{hldData.hld?.title || 'High-Level Design'}</h2>
            <p className="text-xs text-text-muted">AI-generated architecture document</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => onCopyWithFeedback(hldData.markdown || '', 'hld-md')} variant="ghost" size="sm" icon={copyFeedback['hld-md'] ? Check : FileText}>
            {copyFeedback['hld-md'] ? 'Copied!' : 'Copy MD'}
          </Button>
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

      {/* HLD Document Export */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-3 bg-surface rounded-xl border border-border mb-4">
        <div className="flex items-center gap-3">
          <Download className="w-5 h-5 text-cta" />
          <div>
            <p className="text-xs font-semibold text-text-primary">Export Document</p>
            <p className="text-[10px] text-text-muted">Download as a formatted document</p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <label className="flex items-center gap-1.5 text-[10px] text-text-secondary cursor-pointer mr-2">
            <input
              type="checkbox"
              checked={hldIncludeDiagrams}
              onChange={e => onSetHldIncludeDiagrams(e.target.checked)}
              className="accent-cta w-3 h-3"
            />
            Include diagrams
          </label>
          {DOC_EXPORT_FORMATS.map(f => (
            <Button
              key={f.id}
              onClick={() => onHldExport(f.id)}
              variant="secondary"
              size="sm"
              loading={hldExportLoading[f.id]}
              icon={copyFeedback[`hld-${f.id}`] ? Check : Download}
            >
              <span className={copyFeedback[`hld-${f.id}`] ? 'text-cta' : ''}>
                {copyFeedback[`hld-${f.id}`] ? 'Downloaded!' : f.label}
              </span>
            </Button>
          ))}
        </div>
      </div>

      {/* HLD Tabs */}
      <div className="flex gap-1 mb-4 border-b border-border pb-2">
        {HLD_TABS.map(t => (
          <button key={t.id} onClick={() => onSetHldTab(t.id)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer flex items-center gap-1.5 ${
              hldTab === t.id ? 'bg-cta/15 text-cta' : 'text-text-muted hover:text-text-primary'
            }`}><t.icon className="w-3 h-3" />{t.label}</button>
        ))}
      </div>

      {/* Tab Content */}
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
                  {svc.estimated_monthly_cost && <span>~${svc.estimated_monthly_cost}/mo</span>}
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

        {/* FinOps tab content hidden during beta — no money-related UI */}

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
  );
}
