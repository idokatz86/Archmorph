import React from 'react';
import { Download } from 'lucide-react';
import { Button, Card } from '../ui';

const EXPORT_FORMATS = [
  { id: 'architecture-package-html', label: 'HTML Package' },
  { id: 'architecture-package-svg', label: 'Target SVG' },
  { id: 'architecture-package-svg-dr', label: 'DR SVG' },
];

export default function ExportPanel({ exportLoading, onExportDiagram }) {
  return (
    <Card className="p-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-text-primary mb-1">Export Architecture Package</h3>
          <p className="text-xs text-text-muted">Download the customer-ready HTML package or focused SVG topology outputs</p>
        </div>
        <div className="flex items-center gap-2">
          {EXPORT_FORMATS.map(f => (
            <Button key={f.id} onClick={() => onExportDiagram(f.id)} variant="secondary" size="sm" loading={exportLoading[f.id]} icon={Download}>
              {f.label}
            </Button>
          ))}
        </div>
      </div>
    </Card>
  );
}
