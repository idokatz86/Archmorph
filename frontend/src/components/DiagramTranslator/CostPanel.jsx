import React, { useState, useCallback, useEffect } from 'react';
import { BarChart3, Info, Download, TrendingDown } from 'lucide-react';
import { Card } from '../ui';

const RESERVED_OPTIONS = [
  { value: 'none', label: 'Pay-as-you-go' },
  { value: '1yr', label: '1yr Reserved' },
  { value: '3yr', label: '3yr Reserved' },
];

const RI_DISCOUNTS = { none: 0, '1yr': 0.30, '3yr': 0.50 };

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

  if (!costEstimate) return null;

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

          {/* RI Savings Summary */}
          {savingsSummary && savingsSummary.payg > 0 && (
            <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3 mb-4 border border-green-200 dark:border-green-800">
              <div className="flex items-center gap-1.5 mb-2">
                <TrendingDown className="w-4 h-4 text-green-600" />
                <span className="text-xs font-semibold text-green-700 dark:text-green-400">Reserved Instance Savings</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <p className="text-text-muted">1yr RI</p>
                  <p className="font-medium text-green-700 dark:text-green-400">Save ${savingsSummary.savings1yr.toLocaleString()}/mo (30%)</p>
                </div>
                <div>
                  <p className="text-text-muted">3yr RI</p>
                  <p className="font-medium text-green-700 dark:text-green-400">Save ${savingsSummary.savings3yr.toLocaleString()}/mo (50%)</p>
                </div>
              </div>
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
