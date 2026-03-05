import React, { useState } from 'react';
import {
  BarChart3, ChevronDown, ChevronUp, DollarSign, Info, Lightbulb,
  ArrowLeft, Loader2, TrendingDown, MapPin, ExternalLink, Shield, Layers,
} from 'lucide-react';
import { Button, Card, Badge } from '../ui';

/* ── Per-Service Breakdown Row ─────────────────────────── */
function ServiceRow({ svc }) {
  const [open, setOpen] = useState(false);
  const low = svc.monthly_low || 0;
  const mid = svc.monthly_mid || 0;
  const high = svc.monthly_high || 0;

  return (
    <div className="border-b border-border last:border-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-secondary/30 transition-colors cursor-pointer text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <DollarSign className="w-4 h-4 text-cta shrink-0" />
          <div>
            <p className="text-sm font-medium text-text-primary">{svc.service}</p>
            {svc.sku && <p className="text-xs text-text-muted">{svc.sku}</p>}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-text-primary">
            ${low.toLocaleString()} – ${high.toLocaleString()}
          </span>
          {open ? <ChevronUp className="w-4 h-4 text-text-muted" /> : <ChevronDown className="w-4 h-4 text-text-muted" />}
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 animate-in fade-in slide-in-from-top-1">
          {/* Formula */}
          {svc.formula && (
            <div className="bg-surface rounded-lg p-3">
              <p className="text-xs font-semibold text-text-secondary mb-1">Price Formula</p>
              <p className="text-xs text-text-muted font-mono">{svc.formula}</p>
            </div>
          )}

          {/* Assumptions */}
          {/* Assumptions */}
          {Array.isArray(svc.assumptions) && svc.assumptions.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-text-secondary mb-1">Assumptions</p>
              <ul className="space-y-0.5">
                {svc.assumptions.map((a, i) => (
                  <li key={i} className="text-xs text-text-muted flex items-start gap-1.5">
                    <span className="text-cta/60 mt-0.5">•</span> {typeof a === 'string' ? a : JSON.stringify(a)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Alternative SKUs */}
          {Array.isArray(svc.alternatives) && svc.alternatives.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-text-secondary mb-2">Alternative Options</p>
              <div className="grid gap-2">
                {svc.alternatives.map((alt, i) => (
                  <div key={i} className="flex items-center justify-between bg-surface rounded-lg px-3 py-2">
                    <div>
                      <p className="text-xs font-medium text-text-primary">{alt.sku}</p>
                      <p className="text-[11px] text-text-muted">{alt.tradeoff}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs font-semibold text-cta">${alt.monthly?.toLocaleString()}/mo</p>
                      <Badge variant="high" className="text-[10px]">Save {alt.savings}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Optimization Card ──────────────────────────────── */
function OptimizationCard({ opt }) {
  const [expanded, setExpanded] = useState(false);
  const effortColors = { low: 'text-cta', medium: 'text-warning', high: 'text-danger' };
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Lightbulb className="w-5 h-5 text-warning shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-text-primary">{opt.title}</p>
            <p className="text-xs text-text-muted mt-0.5">{opt.description}</p>
          </div>
        </div>
        <div className="text-right shrink-0">
          <Badge variant="high">{opt.savings}</Badge>
          <p className={`text-[10px] mt-1 ${effortColors[opt.effort] || 'text-text-muted'}`}>
            {opt.effort} effort
          </p>
        </div>
      </div>
      {opt.action_steps?.length > 0 && Array.isArray(opt.action_steps) && (
        <div className="mt-2">
          <button onClick={() => setExpanded(!expanded)} className="text-xs text-cta cursor-pointer hover:underline">
            {expanded ? 'Hide steps' : 'Show action steps'}
          </button>
          {expanded && (
            <ol className="mt-2 space-y-1 list-decimal list-inside">
              {opt.action_steps.map((step, i) => (
                <li key={i} className="text-xs text-text-muted">{step}</li>
              ))}
            </ol>
          )}
        </div>
      )}
      {opt.azure_doc_link && (
        <a href={opt.azure_doc_link} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-cta hover:underline mt-2">
          <ExternalLink className="w-3 h-3" /> Learn more
        </a>
      )}
    </Card>
  );
}

/* ── Main Pricing Tab ────────────────────────────────── */
export default function PricingTab({ costBreakdown, loading, onSetStep, onExportPackage, exportingPackage }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-8 h-8 text-cta animate-spin" />
        <span className="ml-3 text-sm text-text-muted">Loading pricing data...</span>
      </div>
    );
  }

  if (!costBreakdown) {
    return (
      <Card className="p-8 text-center">
        <BarChart3 className="w-10 h-10 text-text-muted mx-auto mb-3" />
        <p className="text-sm text-text-muted">Pricing data is loading...</p>
      </Card>
    );
  }

  const { summary, services = [], cost_drivers = [], optimizations = [], cost_by_category = {},
    source_comparison, region_impact, pricing_assumptions: rawAssumptions } = costBreakdown;
  const pricing_assumptions = Array.isArray(rawAssumptions) ? rawAssumptions : [];
  const total = summary?.total_monthly || {};
  const categories = Object.entries(cost_by_category).sort((a, b) => b[1] - a[1]);
  const catTotal = categories.reduce((sum, [, v]) => sum + v, 0);

  return (
    <div className="space-y-6">
      {/* Cost Summary */}
      <Card className="p-6">
        <h2 className="text-lg font-bold text-text-primary flex items-center gap-2 mb-4">
          <BarChart3 className="w-5 h-5 text-cta" /> Estimated Monthly Cost
        </h2>
        <div className="grid grid-cols-3 gap-3 mb-4">
          {[
            { label: 'Low Estimate', value: total.low, color: 'text-cta' },
            { label: 'Mid Estimate', value: total.mid, color: 'text-info' },
            { label: 'High Estimate', value: total.high, color: 'text-warning' },
          ].map(c => (
            <div key={c.label} className="bg-surface rounded-xl p-4 text-center">
              <p className={`text-2xl font-bold ${c.color}`}>
                ${(c.value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </p>
              <p className="text-xs text-text-muted mt-1">{c.label}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-text-muted">
          Region: <span className="font-medium">{summary?.region}</span>
          {summary?.service_count > 0 && <span className="ml-2">• {summary.service_count} services priced</span>}
        </p>
      </Card>

      {/* Cost Drivers */}
      {cost_drivers.length > 0 && (
        <Card className="p-5">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
            <TrendingDown className="w-4 h-4 text-warning" /> Top Cost Drivers
          </h3>
          <div className="space-y-2">
            {cost_drivers.map((d, i) => (
              <div key={i} className="flex items-center justify-between bg-surface rounded-lg px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-warning/15 text-warning text-xs font-bold flex items-center justify-center">
                    {i + 1}
                  </span>
                  <span className="text-sm text-text-primary">{d.service}</span>
                </div>
                <div className="text-right">
                  <span className="text-sm font-semibold text-text-primary">${d.monthly_mid?.toLocaleString()}/mo</span>
                  <span className="text-xs text-text-muted ml-2">({d.percentage}%)</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Cost by Category */}
      {categories.length > 0 && (
        <Card className="p-5">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
            <Layers className="w-4 h-4 text-info" /> Cost by Category
          </h3>
          <div className="space-y-2">
            {categories.map(([cat, amount]) => {
              const pct = catTotal > 0 ? (amount / catTotal) * 100 : 0;
              return (
                <div key={cat}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-text-secondary">{cat}</span>
                    <span className="text-xs font-medium text-text-primary">
                      ${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })} ({pct.toFixed(0)}%)
                    </span>
                  </div>
                  <div className="h-2 bg-secondary rounded-full overflow-hidden">
                    <div
                      className="h-full bg-cta/50 rounded-full transition-all duration-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Source vs Target Comparison */}
      {source_comparison && source_comparison.source_monthly_estimate > 0 && (
        <Card className="p-5">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
            <Shield className="w-4 h-4 text-cta" /> Source vs Azure Cost Comparison
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-surface rounded-xl p-4 text-center">
              <p className="text-xs text-text-muted mb-1">{source_comparison.source_provider?.toUpperCase() || 'Source'} Estimate</p>
              <p className="text-xl font-bold text-text-secondary">
                ${source_comparison.source_monthly_estimate?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </p>
            </div>
            <div className="bg-surface rounded-xl p-4 text-center border-2 border-cta/30">
              <p className="text-xs text-text-muted mb-1">Azure Estimate</p>
              <p className="text-xl font-bold text-cta">
                ${source_comparison.target_monthly_estimate?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </p>
            </div>
          </div>
          {source_comparison.savings_percentage > 0 && (
            <p className="text-xs text-cta font-semibold text-center mt-3">
              ~{source_comparison.savings_percentage}% estimated savings by migrating to Azure
            </p>
          )}
          <p className="text-[10px] text-text-muted text-center mt-1 italic">{source_comparison.note}</p>
        </Card>
      )}

      {/* Region Impact */}
      {region_impact && (
        <Card className="p-5">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
            <MapPin className="w-4 h-4 text-info" /> Region Cost Impact
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-surface rounded-lg p-3 text-center">
              <p className="text-xs text-text-muted mb-1">Current ({region_impact.current_region})</p>
              <p className="text-lg font-bold text-text-primary">${region_impact.current_monthly?.toLocaleString()}/mo</p>
            </div>
            <div className="bg-surface rounded-lg p-3 text-center border border-cta/20">
              <p className="text-xs text-text-muted mb-1">Cheapest ({region_impact.cheapest_region})</p>
              <p className="text-lg font-bold text-cta">${region_impact.cheapest_monthly?.toLocaleString()}/mo</p>
            </div>
          </div>
          <p className="text-xs text-text-muted mt-2">{region_impact.note}</p>
        </Card>
      )}

      {/* Optimization Recommendations */}
      {optimizations.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
            <Lightbulb className="w-4 h-4 text-warning" /> Optimization Recommendations
          </h3>
          <div className="space-y-3">
            {optimizations.map((opt, i) => <OptimizationCard key={i} opt={opt} />)}
          </div>
        </div>
      )}

      {/* Per-Service Breakdown */}
      {services.length > 0 && (
        <Card className="overflow-hidden">
          <div className="px-4 py-3 bg-secondary/50 border-b border-border">
            <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <DollarSign className="w-4 h-4 text-cta" /> Per-Service Breakdown
            </h3>
            <p className="text-xs text-text-muted mt-0.5">Click a service to see formula, assumptions, and alternative SKUs</p>
          </div>
          <div>
            {services.map((svc, i) => <ServiceRow key={i} svc={svc} />)}
          </div>
        </Card>
      )}

      {/* Pricing Assumptions */}
      {pricing_assumptions.length > 0 && (
        <Card className="p-4">
          <h3 className="text-xs font-semibold text-text-secondary flex items-center gap-2 mb-2">
            <Info className="w-3.5 h-3.5 text-text-muted" /> Pricing Assumptions
          </h3>
          <ul className="space-y-1">
            {pricing_assumptions.map((a, i) => (
              <li key={i} className="text-[11px] text-text-muted flex items-start gap-1.5">
                <span className="text-cta/60 mt-0.5">•</span> {a}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <Button onClick={() => onSetStep('hld')} variant="ghost" icon={ArrowLeft}>
          Back to HLD
        </Button>
        {onExportPackage && (
          <Button onClick={onExportPackage} variant="primary" icon={DollarSign} loading={exportingPackage}>
            Download Migration Package
          </Button>
        )}
      </div>
    </div>
  );
}
