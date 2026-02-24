import React from 'react';
import {
  ArrowRight, AlertTriangle, Info, HelpCircle,
  FileCode, Sparkles,
} from 'lucide-react';
import { Badge, Button, Card } from '../ui';
import ExportPanel from './ExportPanel';
import HLDPanel from './HLDPanel';

export default function AnalysisResults({
  analysis, loading, iacFormat, exportLoading, hldLoading,
  hldData, hldTab, hldExportLoading, hldIncludeDiagrams, copyFeedback,
  onSetStep, onGenerateIac, onGenerateHld, onExportDiagram,
  onSetHldTab, onSetHldIncludeDiagrams, onHldExport, onCopyWithFeedback,
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
                    <div key={i} className="px-4 py-3 flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-sm font-medium ${analysis.source_provider === 'gcp' ? 'text-[#EA4335]' : 'text-[#FF9900]'}`}>{m.source_service}</span>
                          <ArrowRight className="w-3.5 h-3.5 text-text-muted shrink-0" />
                          <span className="text-sm text-info font-medium">{m.azure_service}</span>
                        </div>
                      </div>
                      <Badge variant={m.confidence >= 0.9 ? 'high' : m.confidence >= 0.8 ? 'medium' : 'low'}>
                        {(m.confidence * 100).toFixed(0)}%
                      </Badge>
                    </div>
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

      {/* Generate Buttons */}
      <div className="flex items-center justify-between">
        <Button onClick={() => onSetStep('questions')} variant="ghost" icon={HelpCircle}>Back to Questions</Button>
        <div className="flex items-center gap-2">
          <Button onClick={() => onGenerateIac('terraform')} loading={loading && iacFormat === 'terraform'} icon={FileCode}>Generate Terraform</Button>
          <Button onClick={() => onGenerateIac('bicep')} variant="secondary" loading={loading && iacFormat === 'bicep'} icon={FileCode}>Generate Bicep</Button>
          <Button onClick={() => onGenerateIac('cloudformation')} variant="secondary" loading={loading && iacFormat === 'cloudformation'} icon={FileCode}>CloudFormation</Button>
          <Button onClick={onGenerateHld} loading={hldLoading} variant="secondary" icon={Sparkles}>Generate HLD</Button>
        </div>
      </div>

      {/* HLD Document */}
      <HLDPanel
        hldData={hldData}
        hldTab={hldTab}
        hldExportLoading={hldExportLoading}
        hldIncludeDiagrams={hldIncludeDiagrams}
        copyFeedback={copyFeedback}
        onSetHldTab={onSetHldTab}
        onSetHldIncludeDiagrams={onSetHldIncludeDiagrams}
        onHldExport={onHldExport}
        onCopyWithFeedback={onCopyWithFeedback}
      />
    </div>
  );
}
