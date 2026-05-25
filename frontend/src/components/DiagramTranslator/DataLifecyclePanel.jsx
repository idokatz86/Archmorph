import React from 'react';
import { Clock, Download, ShieldCheck, Trash2 } from 'lucide-react';
import { Button, Card } from '../ui';

function formatTimestamp(value) {
  if (!value) return 'Pending';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function formatDuration(seconds) {
  if (!seconds) return 'Not issued';
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return `${hours}h`;
}

function normalizeReceipt({ diagramId, analysis, exportCapability, purgeReceipt }) {
  if (purgeReceipt && (!diagramId || purgeReceipt.diagram_id === diagramId)) return purgeReceipt;
  if (analysis?.trust_receipt) return analysis.trust_receipt;
  if (!diagramId) return null;
  return {
    schema_version: 'client-fallback',
    receipt_id: `client-${diagramId}`,
    correlation_id: diagramId,
    diagram_id: diagramId,
    status: 'active',
    retention: {
      class: null,
      customer_content_ttl_seconds: null,
      uploaded_at: null,
      expires_at: null,
    },
    export_capability: {
      status: exportCapability ? 'issued' : 'not_issued',
      expires_in_seconds: null,
    },
    ai_processing: {
      processor: null,
      training_use: null,
    },
    artifacts: {
      uploaded_content: 'present',
      analysis_session: analysis ? 'present' : 'not_present',
    },
    purge: {
      status: 'not_requested',
      server_content_deleted: false,
      client_cache_action: 'clear_session_storage_after_successful_purge',
    },
    audit_security_logs: {
      retained: null,
      contains_customer_content: null,
      retention_days: null,
    },
  };
}

function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function artifactSummary(artifacts = {}) {
  const uploaded = artifacts.uploaded_content || 'not_present';
  const session = artifacts.analysis_session || 'not_present';
  return `Upload: ${uploaded} / Analysis: ${session}`;
}

function auditLogSummary(auditSecurityLogs = {}) {
  if (auditSecurityLogs.retained === true) {
    return `Audit/security logs retained${auditSecurityLogs.contains_customer_content === false ? ' / no customer content' : ''}`;
  }
  if (auditSecurityLogs.retained === false) return 'Not retained';
  return 'Not available';
}

export default function DataLifecyclePanel({
  diagramId,
  analysis,
  exportCapability,
  purgeReceipt,
  purgeLoading = false,
  onPurge,
}) {
  const receipt = normalizeReceipt({ diagramId, analysis, exportCapability, purgeReceipt });
  if (!receipt) return null;

  const isPurged = receipt.status === 'purged' || receipt.purge?.status === 'purged';
  const receiptDiagramId = receipt.diagram_id || diagramId;
  const filename = `archmorph-trust-receipt-${receiptDiagramId || 'analysis'}.json`;

  return (
    <Card className={`p-4 ${isPurged ? 'border-cta/30 bg-cta/5' : 'border-info/25 bg-info/5'}`}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-cta" aria-hidden="true" />
            <h2 className="text-base font-semibold text-text-primary">Data lifecycle receipt</h2>
          </div>
          <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs font-medium text-text-muted">Correlation ID</dt>
              <dd className="mt-1 truncate font-mono text-xs text-text-primary">{receipt.correlation_id || receiptDiagramId}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-text-muted">Uploaded</dt>
              <dd className="mt-1 text-sm text-text-primary">{formatTimestamp(receipt.retention?.uploaded_at)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-text-muted">Content expiry</dt>
              <dd className="mt-1 flex items-center gap-1.5 text-sm text-text-primary">
                <Clock className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
                {formatTimestamp(receipt.retention?.expires_at)}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-text-muted">Retention class</dt>
              <dd className="mt-1 text-sm text-text-primary">{receipt.retention?.class || 'Not available'}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-text-muted">Export capability</dt>
              <dd className="mt-1 text-sm text-text-primary">{formatDuration(receipt.export_capability?.expires_in_seconds)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-text-muted">AI processing</dt>
              <dd className="mt-1 text-sm text-text-primary">{receipt.ai_processing?.processor || 'Not available'}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-text-muted">Backend artifacts</dt>
              <dd className="mt-1 text-sm text-text-primary">{artifactSummary(receipt.artifacts)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-text-muted">Purge status</dt>
              <dd className="mt-1 text-sm text-text-primary">{isPurged ? 'Purged' : 'Available'}</dd>
            </div>
            <div className="sm:col-span-2 lg:col-span-4">
              <dt className="text-xs font-medium text-text-muted">Audit/security logs</dt>
              <dd className="mt-1 text-sm text-text-primary">
                {auditLogSummary(receipt.audit_security_logs)}
              </dd>
            </div>
          </dl>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={Download}
            onClick={() => downloadJson(filename, receipt)}
          >
            Download Receipt
          </Button>
          {diagramId && onPurge && !isPurged && (
            <Button
              variant="danger"
              size="sm"
              icon={Trash2}
              loading={purgeLoading}
              onClick={onPurge}
            >
              Purge Current Analysis
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}