/**
 * Migration Risk Score panel (#158).
 *
 * Displays a circular risk gauge, factor breakdown cards, tier badge,
 * and actionable recommendations for a given diagram analysis.
 */

import React, { useState, useCallback } from 'react';
import { ShieldAlert, TrendingDown, AlertTriangle, CheckCircle2, Loader2, RefreshCw, Info, ChevronDown, ChevronUp } from 'lucide-react';
import { Card, Badge, Button } from './ui';
import api from '../services/apiClient';

const TIER_COLORS = {
  low: { stroke: '#22c55e', bg: 'bg-green-500/15', text: 'text-green-400', label: 'Low Risk' },
  moderate: { stroke: '#eab308', bg: 'bg-yellow-500/15', text: 'text-yellow-400', label: 'Moderate Risk' },
  high: { stroke: '#f97316', bg: 'bg-orange-500/15', text: 'text-orange-400', label: 'High Risk' },
  critical: { stroke: '#ef4444', bg: 'bg-red-500/15', text: 'text-red-400', label: 'Critical Risk' },
};

function RiskGauge({ score, tier }) {
  const colors = TIER_COLORS[tier] || TIER_COLORS.moderate;
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  const progress = (score / 100) * circumference;

  return (
    <div className="flex flex-col items-center">
      <svg width="180" height="180" viewBox="0 0 200 200" className="drop-shadow-lg">
        <circle cx="100" cy="100" r={radius} fill="none" stroke="currentColor" strokeWidth="12" className="text-border" />
        <circle
          cx="100"
          cy="100"
          r={radius}
          fill="none"
          stroke={colors.stroke}
          strokeWidth="12"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          strokeLinecap="round"
          transform="rotate(-90 100 100)"
          className="transition-all duration-1000 ease-out"
        />
        <text x="100" y="92" textAnchor="middle" className="fill-text-primary text-4xl font-bold" style={{ fontSize: '36px' }}>
          {score}
        </text>
        <text x="100" y="118" textAnchor="middle" className="fill-text-muted text-sm" style={{ fontSize: '14px' }}>
          / 100
        </text>
      </svg>
      <span className={`mt-2 px-3 py-1 rounded-full text-sm font-semibold ${colors.bg} ${colors.text}`}>
        {colors.label}
      </span>
    </div>
  );
}

function FactorCard({ name, score, weight, description }) {
  const barWidth = Math.min(score, 100);
  const barColor = score <= 25 ? 'bg-green-500' : score <= 50 ? 'bg-yellow-500' : score <= 75 ? 'bg-orange-500' : 'bg-red-500';

  return (
    <div className="p-3 rounded-lg bg-secondary/50 border border-border">
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-medium text-text-primary capitalize">{name.replace(/_/g, ' ')}</span>
        <span className="text-xs text-text-muted">weight {(weight * 100).toFixed(0)}%</span>
      </div>
      {description && <p className="text-xs text-text-muted mb-2">{description}</p>}
      <div className="flex items-center gap-2">
        <div className="flex-1 h-2 rounded-full bg-border overflow-hidden">
          <div className={`h-full rounded-full ${barColor} transition-all duration-700`} style={{ width: `${barWidth}%` }} />
        </div>
        <span className="text-xs font-mono text-text-secondary w-8 text-right">{score}</span>
      </div>
    </div>
  );
}

export default function MigrationRiskPanel({ diagramId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [recsOpen, setRecsOpen] = useState(true);

  const fetchRisk = useCallback(async () => {
    if (!diagramId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.get(`/diagrams/${diagramId}/risk-score`);
      setData(result);
    } catch (err) {
      setError(err.message || 'Failed to compute risk score');
    } finally {
      setLoading(false);
    }
  }, [diagramId]);

  if (!diagramId) {
    return (
      <Card className="p-6 text-center">
        <ShieldAlert className="w-10 h-10 text-text-muted mx-auto mb-3" />
        <p className="text-sm text-text-muted">Upload a diagram first to compute migration risk.</p>
      </Card>
    );
  }

  if (!data && !loading && !error) {
    return (
      <Card className="p-6 text-center">
        <ShieldAlert className="w-10 h-10 text-cta mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-text-primary mb-2">Migration Risk Assessment</h3>
        <p className="text-sm text-text-muted mb-4">Analyze potential risks across 6 weighted factors before starting your migration.</p>
        <Button onClick={fetchRisk} icon={TrendingDown}>Compute Risk Score</Button>
      </Card>
    );
  }

  if (loading) {
    return (
      <Card className="p-8 flex items-center justify-center gap-3">
        <Loader2 className="w-5 h-5 text-cta animate-spin" />
        <span className="text-sm text-text-muted">Computing migration risk…</span>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="p-6 text-center">
        <AlertTriangle className="w-8 h-8 text-danger mx-auto mb-2" />
        <p className="text-sm text-danger mb-3">{error}</p>
        <Button onClick={fetchRisk} variant="secondary" icon={RefreshCw} size="sm">Retry</Button>
      </Card>
    );
  }

  const { overall_score, tier, factors, recommendations } = data;

  return (
    <div className="space-y-6">
      {/* Header + Gauge */}
      <Card className="p-6">
        <div className="flex flex-col md:flex-row items-center gap-6">
          <RiskGauge score={overall_score} tier={tier} />
          <div className="flex-1 text-center md:text-left">
            <h3 className="text-xl font-bold text-text-primary mb-1">Migration Risk Score</h3>
            <p className="text-sm text-text-muted mb-3">
              Aggregated risk across {Object.keys(factors).length} weighted factors for this architecture.
            </p>
            <Button onClick={fetchRisk} variant="ghost" icon={RefreshCw} size="sm">Recalculate</Button>
          </div>
        </div>
      </Card>

      {/* Factor Breakdown */}
      <Card className="p-5">
        <h4 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-3">Factor Breakdown</h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {Object.entries(factors).map(([name, f]) => (
            <FactorCard key={name} name={name} score={f.score} weight={f.weight} description={f.description} />
          ))}
        </div>
      </Card>

      {/* Recommendations */}
      {recommendations && recommendations.length > 0 && (
        <Card className="p-5">
          <button
            className="w-full flex items-center justify-between text-sm font-semibold text-text-secondary uppercase tracking-wider cursor-pointer"
            onClick={() => setRecsOpen(!recsOpen)}
          >
            <span className="flex items-center gap-2">
              <Info className="w-4 h-4" />
              Recommendations ({recommendations.length})
            </span>
            {recsOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
          {recsOpen && (
            <ul className="mt-3 space-y-2">
              {recommendations.map((rec, idx) => (
                <li key={idx} className="flex items-start gap-2 text-sm">
                  <CheckCircle2 className="w-4 h-4 text-cta mt-0.5 shrink-0" />
                  <span className="text-text-primary">{rec.description || rec}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
