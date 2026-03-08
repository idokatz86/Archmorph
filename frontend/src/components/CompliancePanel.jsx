/**
 * Compliance Assessment panel (#160).
 *
 * Displays compliance framework scores, gap analysis, and
 * remediation guidance for a given diagram analysis.
 */

import React, { useState, useCallback } from 'react';
import { Shield, ShieldCheck, ShieldX, Loader2, AlertTriangle, RefreshCw, ChevronDown, ChevronUp, ExternalLink } from 'lucide-react';
import { Card, Badge, Button } from './ui';
import api from '../services/apiClient';

const FRAMEWORK_ICONS = {
  HIPAA: '🏥',
  'PCI-DSS': '💳',
  'SOC 2': '🔒',
  GDPR: '🇪🇺',
  'ISO 27001': '📋',
  FedRAMP: '🏛️',
};

function ScoreRing({ score, size = 48 }) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = (score / 100) * circumference;
  const color = score >= 80 ? '#22c55e' : score >= 50 ? '#eab308' : '#ef4444';

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="currentColor" strokeWidth="4" className="text-border" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth="4"
        strokeDasharray={circumference}
        strokeDashoffset={circumference - progress}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="transition-all duration-700"
      />
      <text x={size / 2} y={size / 2 + 5} textAnchor="middle" className="fill-text-primary font-bold" style={{ fontSize: '13px' }}>
        {score}%
      </text>
    </svg>
  );
}

function FrameworkCard({ framework }) {
  const [open, setOpen] = useState(false);
  const icon = FRAMEWORK_ICONS[framework.framework] || '📋';
  const gapCount = framework.gaps?.length || 0;

  return (
    <Card className="p-4">
      <div className="flex items-center gap-3">
        <ScoreRing score={framework.score} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg">{icon}</span>
            <h4 className="text-sm font-semibold text-text-primary truncate">{framework.framework}</h4>
          </div>
          <p className="text-xs text-text-muted mt-0.5">
            {framework.controls_met}/{framework.total_controls} controls met
            {gapCount > 0 && <span className="text-warning ml-1">• {gapCount} gap{gapCount !== 1 ? 's' : ''}</span>}
          </p>
        </div>
        {gapCount > 0 && (
          <button onClick={() => setOpen(!open)} aria-label={open ? 'Collapse compliance gaps' : 'Expand compliance gaps'} className="text-text-muted hover:text-text-primary cursor-pointer">
            {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        )}
      </div>

      {/* Gap details */}
      {open && framework.gaps && (
        <div className="mt-3 pt-3 border-t border-border space-y-2">
          {framework.gaps.map((gap, i) => (
            <div key={i} className="p-2 rounded-lg bg-secondary/50">
              <div className="flex items-center gap-2 mb-1">
                <ShieldX className="w-3.5 h-3.5 text-danger shrink-0" />
                <span className="text-xs font-medium text-text-primary">{gap.control || gap.gap_id}</span>
                <Badge variant={gap.severity === 'critical' ? 'low' : gap.severity === 'high' ? 'low' : 'medium'}>
                  {gap.severity}
                </Badge>
              </div>
              <p className="text-xs text-text-muted ml-5.5 pl-0.5">{gap.description}</p>
              {gap.remediation && (
                <p className="text-xs text-cta ml-5.5 pl-0.5 mt-1">{gap.remediation}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function CompliancePanel({ diagramId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchCompliance = useCallback(async () => {
    if (!diagramId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.get(`/diagrams/${diagramId}/compliance`);
      setData(result);
    } catch (err) {
      setError(err.message || 'Compliance assessment failed');
    } finally {
      setLoading(false);
    }
  }, [diagramId]);

  if (!diagramId) {
    return (
      <Card className="p-6 text-center">
        <Shield className="w-10 h-10 text-text-muted mx-auto mb-3" />
        <p className="text-sm text-text-muted">Upload a diagram first to run compliance checks.</p>
      </Card>
    );
  }

  if (!data && !loading && !error) {
    return (
      <Card className="p-6 text-center">
        <ShieldCheck className="w-10 h-10 text-cta mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-text-primary mb-2">Compliance Assessment</h3>
        <p className="text-sm text-text-muted mb-4">Check your architecture against HIPAA, PCI-DSS, SOC 2, GDPR, ISO 27001, and FedRAMP.</p>
        <Button onClick={fetchCompliance} icon={ShieldCheck}>Run Assessment</Button>
      </Card>
    );
  }

  if (loading) {
    return (
      <Card className="p-8 flex items-center justify-center gap-3">
        <Loader2 className="w-5 h-5 text-cta animate-spin" />
        <span className="text-sm text-text-muted">Running compliance checks…</span>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="p-6 text-center">
        <AlertTriangle className="w-8 h-8 text-danger mx-auto mb-2" />
        <p className="text-sm text-danger mb-3">{error}</p>
        <Button onClick={fetchCompliance} variant="secondary" icon={RefreshCw} size="sm">Retry</Button>
      </Card>
    );
  }

  const { overall_score, frameworks, total_gaps, critical_gaps } = data;

  return (
    <div className="space-y-5">
      {/* Summary */}
      <Card className="p-6">
        <div className="flex flex-col sm:flex-row items-center gap-6">
          <ScoreRing score={overall_score} size={80} />
          <div className="flex-1 text-center sm:text-left">
            <h3 className="text-xl font-bold text-text-primary mb-1">Compliance Score</h3>
            <p className="text-sm text-text-muted">
              {frameworks?.length || 0} frameworks assessed •{' '}
              {total_gaps > 0 ? (
                <span className="text-warning">{total_gaps} gap{total_gaps !== 1 ? 's' : ''} found</span>
              ) : (
                <span className="text-green-400">No gaps detected</span>
              )}
              {critical_gaps > 0 && <span className="text-danger ml-1">({critical_gaps} critical)</span>}
            </p>
          </div>
          <Button onClick={fetchCompliance} variant="ghost" icon={RefreshCw} size="sm">Refresh</Button>
        </div>
      </Card>

      {/* Framework cards */}
      {frameworks && frameworks.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {frameworks.map((fw) => (
            <FrameworkCard key={fw.framework} framework={fw} />
          ))}
        </div>
      )}
    </div>
  );
}
