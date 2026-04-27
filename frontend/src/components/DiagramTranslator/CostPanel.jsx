import React, { useState, useCallback, useEffect, useMemo } from 'react';
import { BarChart3, Info, Download, TrendingDown, PieChart } from 'lucide-react';
import { Card, EmptyState, ProgressBar } from '../ui';

const RESERVED_OPTIONS = [
  { value: 'none', label: 'Pay-as-you-go' },
  { value: '1yr', label: '1yr Reserved' },
  { value: '3yr', label: '3yr Reserved' },
];

const RI_DISCOUNTS = { none: 0, '1yr': 0.30, '3yr': 0.50 };

/* ── Wave 3: Cost Bar Chart (#515) ── */
function CostBarChart({ services, maxCost }) {
  const sorted = [...services].sort((a, b) => (b.monthly_high || 0) - (a.monthly_high || 0)).slice(0, 12);
  return (
    <div className="space-y-2">
      {sorted.map((s, i) => {
        const pct = maxCost > 0 ? ((s.monthly_high || 0) / maxCost) * 100 : 0;
        return (
          <div key={i} className="stagger-item">
            <div className="flex items-center justify-between text-xs mb-0.5">
              <span className="text-text-secondary truncate max-w-[60%]">{s.service}</span>
              <span className="font-mono text-text-primary font-medium">${(s.monthly_high || 0).toLocaleString()}</span>
            </div>
            <div className="h-2 bg-secondary rounded-full overflow-hidden">
              <div className="h-full bg-cta rounded-full transition-all duration-700 ease-out" style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Wave 3: Cost Donut Chart (#515) ── */
function CostDonut({ categories }) {
  const COLORS = ['#22C55E', '#3B82F6', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#F97316'];
  const total = categories.reduce((sum, c) => sum + c.cost, 0);
  if (total === 0) return null;

  let cumulative = 0;
  const segments = categories.map((cat, i) => {
    const pct = (cat.cost / total) * 100;
    const startAngle = (cumulative / 100) * 360;
    cumulative += pct;
    const endAngle = (cumulative / 100) * 360;
    const largeArc = pct > 50 ? 1 : 0;
    const toRad = (d) => (d - 90) * (Math.PI / 180);
    const r = 40;
    const x1 = 50 + r * Math.cos(toRad(startAngle));
    const y1 = 50 + r * Math.sin(toRad(startAngle));
    const x2 = 50 + r * Math.cos(toRad(endAngle));
    const y2 = 50 + r * Math.sin(toRad(endAngle));
    return { ...cat, color: COLORS[i % COLORS.length], pct, d: `M 50 50 L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z` };
  });

  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 100 100" className="w-24 h-24 flex-shrink-0" aria-label="Cost distribution by category">
        {segments.map((seg, i) => (
          <path key={i} d={seg.d} fill={seg.color} opacity={0.85} className="transition-opacity hover:opacity-100" />
        ))}
        <circle cx="50" cy="50" r="22" fill="var(--color-surface)" />
        <text x="50" y="48" textAnchor="middle" className="text-[8px] font-bold fill-text-primary">${Math.round(total).toLocaleString()}</text>
        <text x="50" y="57" textAnchor="middle" className="text-[5px] fill-text-muted">/month</text>
      </svg>
      <div className="flex flex-col gap-1 text-xs min-w-0">
        {segments.map((seg, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: seg.color }} />
            <span className="text-text-secondary truncate">{seg.name}</span>
            <span className="text-text-muted ml-auto font-mono">{Math.round(seg.pct)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Wave 3: Cost Comparison Card (#515) ── */
function CostComparisonCard({ payg, ri1yr, ri3yr }) {
  if (!payg || payg <= 0) return null;
  return (
    <div className="grid grid-cols-3 gap-2">
      <div className="bg-surface rounded-lg p-3 text-center border border-border">
        <p className="text-xs text-text-muted mb-1">Pay-as-you-go</p>
        <p className="text-base font-bold text-text-primary">${payg.toLocaleString()}</p>
        <p className="text-[10px] text-text-muted">/month</p>
      </div>
      <div className="bg-surface rounded-lg p-3 text-center border border-cta/30">
        <p className="text-xs text-text-muted mb-1">1yr Reserved</p>
        <p className="text-base font-bold text-cta">${ri1yr.toLocaleString()}</p>
        <p className="text-[10px] text-cta">save 30%</p>
      </div>
      <div className="bg-surface rounded-lg p-3 text-center border border-cta/50">
        <p className="text-xs text-text-muted mb-1">3yr Reserved</p>
        <p className="text-base font-bold text-cta">${ri3yr.toLocaleString()}</p>
        <p className="text-[10px] text-cta">save 50%</p>
      </div>
    </div>
  );
}

export default function CostPanel({ costEstimate, diagramId, api }) {
  const [overrides, setOverrides] = useState({});
  const [configured, setConfigured] = useState(null);
  const [savingsSummary, setSavingsSummary] = useState(null);

  const totalLow = (configured || costEstimate)?.total_monthly_estimate?.low ?? 0;
  const totalHigh = (configured || costEstimate)?.total_monthly_estimate?.high ?? 0;
  const services = (configured || costEstimate)?.services || [];
  const pricedServices = services.filter(s => (s.monthly_low || 0) + (s.monthly_high || 0) > 0);
  const unpricedServices = services.filter(s => (s.monthly_low || 0) + (s.monthly_high || 0) === 0);
  const hasPricing = totalLow > 0 || totalHigh > 0 || pricedServices.length > 0;
  const displayEstimate = configured || costEstimate;

  // Recalculate locally when overrides change
  const recalculate = useCallback(() => {
    if (!costEstimate?.services?.length) return;
    const updated = costEstimate.services.map(svc => {
      const name = svc.service;
      const o = overrides[name] || {};
      const count = o.instance_count || 1;
      const term = o.reserved_term || 'none';
      const discount = RI_DISCOUNTS[term] || 0;
      const adjLow = Math.round(svc.monthly_low * count * (1 - discount) * 100) / 100;
      const adjHigh = Math.round(svc.monthly_high * count * (1 - discount) * 100) / 100;
      const paygMid = (svc.monthly_low + svc.monthly_high) / 2 * count;
      const adjMid = (adjLow + adjHigh) / 2;
      return {
        ...svc,
        instance_count: count,
        reserved_term: term,
        monthly_low: adjLow,
        monthly_high: adjHigh,
        ri_savings: Math.round((paygMid - adjMid) * 100) / 100,
      };
    });
    const tLow = updated.reduce((s, x) => s + x.monthly_low, 0);
    const tHigh = updated.reduce((s, x) => s + x.monthly_high, 0);
    setConfigured({
      ...costEstimate,
      services: updated,
      total_monthly_estimate: { low: Math.round(tLow * 100) / 100, high: Math.round(tHigh * 100) / 100 },
    });

    // Savings summary
    const paygTotal = costEstimate.services.reduce((s, x) => {
      const c = (overrides[x.service] || {}).instance_count || 1;
      return s + ((x.monthly_low + x.monthly_high) / 2) * c;
    }, 0);
    const ri1yr = paygTotal * 0.70;
    const ri3yr = paygTotal * 0.50;
    setSavingsSummary({
      payg: Math.round(paygTotal * 100) / 100,
      ri1yr: Math.round(ri1yr * 100) / 100,
      ri3yr: Math.round(ri3yr * 100) / 100,
      savings1yr: Math.round((paygTotal - ri1yr) * 100) / 100,
      savings3yr: Math.round((paygTotal - ri3yr) * 100) / 100,
    });
  }, [costEstimate, overrides]);

  useEffect(() => { recalculate(); }, [recalculate]);

  const updateOverride = (service, field, value) => {
    setOverrides(prev => ({
      ...prev,
      [service]: { ...prev[service], [field]: value },
    }));
  };

  const handleExportCSV = async () => {
    if (!diagramId || !api) return;
    try {
      // Save overrides first
      const overrideList = Object.entries(overrides).map(([service, o]) => ({
        service,
        instance_count: o.instance_count || 1,
        sku: o.sku || null,
        reserved_term: o.reserved_term || 'none',
      }));
      if (overrideList.length) {
        await api.post(`/diagrams/${diagramId}/cost-estimate/configure`, { overrides: overrideList });
      }
      // Download CSV
      const resp = await api.get(`/diagrams/${diagramId}/cost-estimate/export`, { responseType: 'blob' });
      const blob = resp instanceof Blob ? resp : new Blob([resp], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `cost-estimate-${diagramId}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      // Silently fail — user can retry
    }
  };

  // Group services by category for donut chart
  const categoryGroups = useMemo(() => {
    const groups = {};
    pricedServices.forEach(s => {
      const name = s.service?.toLowerCase() || '';
      const cat = name.includes('sql') || name.includes('storage') || name.includes('cosmos') || name.includes('redis') ? 'Data'
        : name.includes('function') || name.includes('app service') || name.includes('container') || name.includes('vm') ? 'Compute'
        : name.includes('vnet') || name.includes('gateway') || name.includes('cdn') || name.includes('front door') || name.includes('load') ? 'Networking'
        : name.includes('key vault') || name.includes('firewall') || name.includes('sentinel') || name.includes('defender') ? 'Security'
        : name.includes('monitor') || name.includes('insight') || name.includes('log') ? 'Monitoring'
        : 'Other';
      if (!groups[cat]) groups[cat] = 0;
      groups[cat] += (s.monthly_high || 0);
    });
    return Object.entries(groups).map(([name, cost]) => ({ name, cost })).sort((a, b) => b.cost - a.cost);
  }, [pricedServices]);

  if (!costEstimate) return (
    <Card className="p-6">
      <EmptyState
        icon={BarChart3}
        title="Cost Analysis"
        description="Cost estimates will appear here after IaC code is generated. Upload a diagram and generate infrastructure code to see pricing."
      />
    </Card>
  );

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-cta" />
          Estimated Monthly Cost
        </h3>
        {hasPricing && diagramId && api && (
          <button
            onClick={handleExportCSV}
            className="flex items-center gap-1 text-xs text-cta hover:text-cta/80 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>
        )}
      </div>
      {displayEstimate?.region && (
        <p className="text-xs text-text-muted mb-3">
          Region: <span className="font-medium text-text-secondary">{displayEstimate.region}</span>
          {displayEstimate?.service_count > 0 && <span className="ml-2">({displayEstimate.service_count} services)</span>}
        </p>
      )}
      {!hasPricing ? (
        <div className="bg-surface rounded-lg p-4 text-center mb-4">
          <p className="text-sm text-text-muted mb-1">Pricing data is not available for the detected services.</p>
          <p className="text-xs text-text-muted">Use the <a href="https://azure.microsoft.com/en-us/pricing/calculator/" target="_blank" rel="noopener noreferrer" className="text-cta hover:underline">Azure Pricing Calculator</a> for accurate estimates.</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="bg-surface rounded-lg p-3 text-center">
              <p className="text-lg font-bold text-cta">${totalLow.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</p>
              <p className="text-xs text-text-muted">Low Estimate</p>
            </div>
            <div className="bg-surface rounded-lg p-3 text-center">
              <p className="text-lg font-bold text-warning">${totalHigh.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</p>
              <p className="text-xs text-text-muted">High Estimate</p>
            </div>
          </div>

          {/* RI Comparison Cards (#515) */}
          {savingsSummary && savingsSummary.payg > 0 && (
            <div className="mb-4">
              <CostComparisonCard payg={savingsSummary.payg} ri1yr={savingsSummary.ri1yr} ri3yr={savingsSummary.ri3yr} />
            </div>
          )}

          {/* Cost Distribution + Bar Chart (#515) */}
          {pricedServices.length > 1 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
              <Card className="p-4 border-border/50">
                <h4 className="text-xs font-semibold text-text-secondary mb-3 flex items-center gap-1.5">
                  <PieChart className="w-3.5 h-3.5" /> Category Distribution
                </h4>
                <CostDonut categories={categoryGroups} />
              </Card>
              <Card className="p-4 border-border/50">
                <h4 className="text-xs font-semibold text-text-secondary mb-3 flex items-center gap-1.5">
                  <BarChart3 className="w-3.5 h-3.5" /> Top Services by Cost
                </h4>
                <CostBarChart services={pricedServices} maxCost={Math.max(...pricedServices.map(s => s.monthly_high || 0), 1)} />
              </Card>
            </div>
          )}

          {/* Per-service configurator */}
          {pricedServices.length > 0 && (
            <div className="space-y-2 max-h-80 overflow-auto">
              {(() => {
                const maxCost = Math.max(...pricedServices.map(s => s.monthly_high || 0), 1);
                return pricedServices.map((s, i) => {
                  const svcOverride = overrides[s.service] || {};
                  return (
                    <div key={i} className="py-2 border-b border-border last:border-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-text-secondary font-medium">{s.service}</span>
                        <span className="text-xs font-medium text-text-primary">
                          ${s.monthly_low?.toLocaleString()} - ${s.monthly_high?.toLocaleString()}
                        </span>
                      </div>
                      <div className="h-1.5 bg-secondary rounded-full overflow-hidden mb-2">
                        <div className="h-full bg-cta/40 rounded-full transition-all duration-500" style={{ width: `${(s.monthly_high / maxCost) * 100}%` }} />
                      </div>
                      {/* Instance count + Reserved capacity controls */}
                      <div className="flex items-center gap-2 flex-wrap">
                        <div className="flex items-center gap-1">
                          <label className="text-[10px] text-text-muted">Instances:</label>
                          <input
                            type="number"
                            min={1}
                            max={1000}
                            value={svcOverride.instance_count || 1}
                            onChange={e => updateOverride(s.service, 'instance_count', Math.max(1, parseInt(e.target.value) || 1))}
                            className="w-14 h-6 text-[11px] text-center rounded border border-border bg-surface text-text-primary"
                          />
                        </div>
                        <div className="flex items-center gap-1">
                          <label className="text-[10px] text-text-muted">Capacity:</label>
                          <select
                            value={svcOverride.reserved_term || 'none'}
                            onChange={e => updateOverride(s.service, 'reserved_term', e.target.value)}
                            className="h-6 text-[11px] rounded border border-border bg-surface text-text-primary px-1"
                          >
                            {RESERVED_OPTIONS.map(opt => (
                              <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                          </select>
                        </div>
                        {s.ri_savings > 0 && (
                          <span className="text-[10px] text-green-600 font-medium">
                            save ${s.ri_savings.toLocaleString()}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          )}
          {unpricedServices.length > 0 && (
            <div className="mt-3 pt-2 border-t border-border">
              <p className="text-[11px] text-text-muted mb-1">{unpricedServices.length} service{unpricedServices.length > 1 ? 's' : ''} without pricing data:</p>
              <p className="text-[11px] text-text-muted">{unpricedServices.map(s => s.service).join(', ')}</p>
            </div>
          )}
        </>
      )}
      <div className="mt-4 pt-3 border-t border-border flex items-start gap-2">
        <Info className="w-3.5 h-3.5 text-text-muted shrink-0 mt-0.5" />
        <p className="text-[11px] text-text-muted leading-relaxed">
          These figures are approximate estimates based on Azure Retail Prices and may not reflect your final costs. Actual charges will vary depending on usage, configuration, reserved capacity, and applicable discounts. For an accurate cost projection, please use the <a href="https://azure.microsoft.com/en-us/pricing/calculator/" target="_blank" rel="noopener noreferrer" className="text-cta hover:underline">Azure Pricing Calculator</a>.
        </p>
      </div>
    </Card>
  );
}
