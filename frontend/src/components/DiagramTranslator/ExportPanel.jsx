import React from 'react';
import { Download } from 'lucide-react';
import { Button, Card } from '../ui';

const EXPORT_FORMATS = [
  { id: 'architecture-package-html', label: 'HTML Package' },
  { id: 'architecture-package-svg', label: 'Target SVG' },
  { id: 'architecture-package-svg-dr', label: 'DR SVG' },
];

export default function ExportPanel({ exportLoading, onExportDiagram, secondary }) {
  return (
    <Card className={`p-4 ${secondary ? 'border-border/60 bg-secondary/30' : 'p-6'}`}>
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h3 className={`font-semibold text-text-primary mb-0.5 ${secondary ? 'text-xs' : 'text-sm'}`}>
            {secondary ? 'Classic Diagram Exports' : 'Export Architecture Package'}
          </h3>
          <p className="text-xs text-text-muted">
            {secondary
              ? 'Standalone SVG and HTML outputs for diagram-only sharing'
              : 'Download the customer-ready HTML package or focused SVG topology outputs'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {EXPORT_FORMATS.map(f => (
            <Button key={f.id} onClick={() => onExportDiagram(f.id)} variant="ghost" size="sm" loading={exportLoading[f.id]} icon={Download}>
              {f.label}
            </Button>
          ))}
        </div>
      </div>
    </Card>
  );
}
