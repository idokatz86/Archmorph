import React, { useState } from 'react';
import { ArrowRight, Eye, Layers, ChevronDown, ChevronUp } from 'lucide-react';
import { Card, Badge } from '../ui';

/**
 * Before/After Architecture Visualization (#250).
 * Shows source → Azure service mapping in a visual comparison layout.
 */
export default function BeforeAfterView({ analysis }) {
  const [expanded, setExpanded] = useState(false);
  if (!analysis?.zones?.length) return null;

  const sourceProvider = (analysis.source_provider || 'aws').toUpperCase();
  const zones = analysis.zones || [];
  const mappings = analysis.mappings || [];

  // Group mappings by zone
  const zoneMap = {};
  for (const m of mappings) {
    const zoneId = (m.notes || '').match(/Zone (\d+)/)?.[1] || '0';
    if (!zoneMap[zoneId]) zoneMap[zoneId] = [];
    zoneMap[zoneId].push(m);
  }

  return (
    <Card className="overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-secondary/30 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <Eye className="w-5 h-5 text-cta" />
          <div className="text-left">
            <h3 className="text-sm font-semibold text-text-primary">Before → After Architecture</h3>
            <p className="text-xs text-text-muted">Visual comparison of {sourceProvider} to Azure migration</p>
          </div>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-text-muted" /> : <ChevronDown className="w-4 h-4 text-text-muted" />}
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-4 border-t border-border pt-4 animate-in fade-in slide-in-from-top-1">
          {/* Header */}
          <div className="grid grid-cols-[1fr_auto_1fr] gap-3 items-center">
            <div className="text-center">
              <Badge variant={sourceProvider.toLowerCase()} className="text-xs">{sourceProvider}</Badge>
              <p className="text-[10px] text-text-muted mt-1">Source Architecture</p>
            </div>
            <ArrowRight className="w-5 h-5 text-cta" />
            <div className="text-center">
              <Badge variant="azure" className="text-xs">AZURE</Badge>
              <p className="text-[10px] text-text-muted mt-1">Target Architecture</p>
            </div>
          </div>

          {/* Per-zone mapping */}
          {zones.map(zone => {
            const zoneMappings = zoneMap[String(zone.id)] || zoneMap[String(zone.number)] || [];
            if (!zoneMappings.length) return null;
            return (
              <div key={zone.id} className="bg-surface rounded-xl border border-border overflow-hidden">
                <div className="px-3 py-2 bg-secondary/30 border-b border-border flex items-center gap-2">
                  <Layers className="w-3.5 h-3.5 text-cta" />
                  <span className="text-xs font-semibold text-text-primary">{zone.name}</span>
                </div>
                <div className="divide-y divide-border">
                  {zoneMappings.map((m, i) => (
                    <div key={i} className="grid grid-cols-[1fr_auto_1fr] gap-2 items-center px-3 py-2">
                      <div className="text-right">
                        <span className={`text-xs font-medium ${sourceProvider === 'GCP' ? 'text-[#EA4335]' : 'text-[#FF9900]'}`}>
                          {m.source_service}
                        </span>
                      </div>
                      <div className="flex flex-col items-center gap-0.5">
                        <ArrowRight className="w-3 h-3 text-text-muted" />
                        <Badge variant={m.confidence >= 0.85 ? 'high' : m.confidence >= 0.6 ? 'medium' : 'low'} className="text-[8px]">
                          {(m.confidence * 100).toFixed(0)}%
                        </Badge>
                      </div>
                      <div>
                        <span className="text-xs font-medium text-info">{m.azure_service}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}

          {/* Summary stats */}
          <div className="grid grid-cols-3 gap-2 pt-2">
            <div className="bg-surface rounded-lg p-2 text-center">
              <p className="text-lg font-bold text-text-primary">{zones.length}</p>
              <p className="text-[10px] text-text-muted">Zones</p>
            </div>
            <div className="bg-surface rounded-lg p-2 text-center">
              <p className="text-lg font-bold text-text-primary">{mappings.length}</p>
              <p className="text-[10px] text-text-muted">Services Mapped</p>
            </div>
            <div className="bg-surface rounded-lg p-2 text-center">
              <p className="text-lg font-bold text-cta">
                {mappings.length > 0 ? `${((mappings.reduce((s, m) => s + (m.confidence || 0), 0) / mappings.length) * 100).toFixed(0)}%` : 'N/A'}
              </p>
              <p className="text-[10px] text-text-muted">Avg Confidence</p>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
