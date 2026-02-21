import React from 'react';
import { BarChart3, Info } from 'lucide-react';
import { Card } from '../ui';

export default function CostPanel({ costEstimate }) {
  if (!costEstimate) return null;

  return (
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
          {(() => {
            const maxCost = Math.max(...costEstimate.services.map(s => s.monthly_high || 0), 1);
            return costEstimate.services.map((s, i) => (
              <div key={i} className="py-1.5 border-b border-border last:border-0">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-text-secondary">{s.service}</span>
                  <span className="text-xs font-medium text-text-primary">${s.monthly_low} - ${s.monthly_high}</span>
                </div>
                <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                  <div className="h-full bg-cta/40 rounded-full transition-all duration-500" style={{ width: `${(s.monthly_high / maxCost) * 100}%` }} />
                </div>
              </div>
            ));
          })()}
        </div>
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
