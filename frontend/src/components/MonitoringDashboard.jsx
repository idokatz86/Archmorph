import React, { useState, useEffect } from 'react';
import {
  Monitor, Server, Clock, Gauge, AlertTriangle, CheckCircle2,
  ArrowUp, ArrowDown, Cpu, HardDrive, Activity, Wifi,
  RefreshCw, Loader2, XCircle,
} from 'lucide-react';
import { Card, Badge } from './ui';
import { API_BASE } from '../constants';

const STATUS_COLORS = {
  healthy: 'text-cta',
  warning: 'text-warning',
  critical: 'text-danger',
};

function getHealthStatus(errorRate) {
  if (errorRate > 10) return 'critical';
  if (errorRate > 3) return 'warning';
  return 'healthy';
}

function formatMs(ms) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function formatNumber(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function ProgressBar({ value, max, color = 'cta', height = 'h-2' }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className={`${height} bg-surface rounded-full overflow-hidden`}>
      <div
        className={`h-full rounded-full bg-${color} transition-all duration-500`}
        style={{ width: `${Math.max(pct, 1)}%` }}
      />
    </div>
  );
}

function MetricTile({ icon: Icon, label, value, sub, color = 'cta' }) {
  return (
    <div className="flex items-center gap-3 p-3 bg-surface rounded-lg">
      <div className={`w-9 h-9 rounded-lg bg-${color}/10 flex items-center justify-center shrink-0`}>
        <Icon className={`w-[18px] h-[18px] text-${color}`} />
      </div>
      <div className="min-w-0">
        <p className="text-lg font-bold text-text-primary leading-tight truncate">{value}</p>
        <p className="text-[10px] text-text-muted leading-tight">{label}</p>
        {sub && <p className="text-[9px] text-text-muted mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

export default function MonitoringDashboard({ sessionToken }) {
  const [data, setData] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const authHeaders = sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {};

  const fetchData = async (showRefreshing = false) => {
    if (showRefreshing) setRefreshing(true);
    try {
      const [monRes, healthRes] = await Promise.all([
        fetch(`${API_BASE}/admin/monitoring`, { headers: authHeaders }),
        fetch(`${API_BASE}/health`),
      ]);
      if (!monRes.ok) throw new Error(`Monitoring API: ${monRes.status}`);
      const [mon, hlth] = await Promise.all([monRes.json(), healthRes.ok ? healthRes.json() : null]);
      setData(mon);
      setHealth(hlth);
      setError(null);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(() => fetchData(), 30000); // Auto-refresh every 30s
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-6 h-6 text-cta animate-spin" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <Card className="p-8 text-center">
        <XCircle className="w-8 h-8 text-danger mx-auto mb-3" />
        <p className="text-sm text-text-primary font-medium">Monitoring Unavailable</p>
        <p className="text-xs text-text-muted mt-1">{error}</p>
        <button
          onClick={() => { setLoading(true); fetchData(); }}
          className="mt-4 px-4 py-1.5 text-xs bg-cta/10 text-cta rounded-lg hover:bg-cta/20 transition-colors"
        >
          Retry
        </button>
      </Card>
    );
  }

  const overview = data?.overview || {};
  const latency = data?.latency || {};
  const statusCodes = data?.status_codes || {};
  const topEndpoints = data?.top_endpoints || [];
  const healthStatus = getHealthStatus(overview.error_rate_pct || 0);

  const maxEndpointRequests = Math.max(...topEndpoints.map(e => e.requests), 1);

  // Status code distribution for mini chart
  const totalStatusCounted = Object.values(statusCodes).reduce((s, v) => s + v, 0);

  return (
    <div className="space-y-6">
      {/* Header with refresh button */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
          <Monitor className="w-4 h-4 text-cta" />
          Application Monitoring
          <Badge variant={healthStatus === 'healthy' ? 'high' : healthStatus === 'warning' ? 'medium' : 'low'}>
            {healthStatus === 'healthy' ? 'Healthy' : healthStatus === 'warning' ? 'Degraded' : 'Critical'}
          </Badge>
        </h3>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-[10px] text-text-muted">
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => fetchData(true)}
            disabled={refreshing}
            className="p-1.5 rounded-lg hover:bg-secondary text-text-muted hover:text-text-primary transition-colors disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Health Overview — 6 tiles */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricTile
          icon={healthStatus === 'healthy' ? CheckCircle2 : AlertTriangle}
          label="Status"
          value={health?.status === 'healthy' ? 'Healthy' : 'Degraded'}
          sub={health?.version ? `v${health.version}` : undefined}
          color={healthStatus === 'healthy' ? 'cta' : 'danger'}
        />
        <MetricTile
          icon={Activity}
          label="Total Requests"
          value={formatNumber(overview.total_requests || 0)}
        />
        <MetricTile
          icon={overview.error_rate_pct > 3 ? AlertTriangle : CheckCircle2}
          label="Error Rate"
          value={`${(overview.error_rate_pct || 0).toFixed(1)}%`}
          sub={`${overview.total_errors || 0} errors`}
          color={overview.error_rate_pct > 10 ? 'danger' : overview.error_rate_pct > 3 ? 'warning' : 'cta'}
        />
        <MetricTile
          icon={Clock}
          label="Uptime"
          value={overview.uptime || '0h 0m'}
        />
        <MetricTile
          icon={Cpu}
          label="Memory"
          value={`${overview.memory_mb || 0} MB`}
          sub={`CPU: ${overview.cpu_percent || 0}%`}
          color="info"
        />
        <MetricTile
          icon={Gauge}
          label="Avg Latency"
          value={latency.avg_ms ? formatMs(latency.avg_ms) : 'N/A'}
          sub={latency.p95_ms ? `P95: ${formatMs(latency.p95_ms)}` : undefined}
          color={latency.p95_ms > 5000 ? 'danger' : latency.p95_ms > 2000 ? 'warning' : 'cta'}
        />
      </div>

      {/* Two-column: Latency Distribution + Error Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Latency Distribution */}
        <Card className="p-5">
          <h4 className="text-xs font-semibold text-text-primary mb-4 flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-cta" />
            Latency Distribution
          </h4>
          {latency.total_samples ? (
            <div className="space-y-3">
              {[
                { label: 'Average', value: latency.avg_ms, color: 'cta' },
                { label: 'P50 (Median)', value: latency.p50_ms, color: 'info' },
                { label: 'P95', value: latency.p95_ms, color: 'warning' },
                { label: 'P99', value: latency.p99_ms, color: 'danger' },
                { label: 'Max', value: latency.max_ms, color: 'danger' },
              ].map(({ label, value, color }) => (
                <div key={label}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] text-text-muted">{label}</span>
                    <span className="text-xs font-bold text-text-primary">{formatMs(value || 0)}</span>
                  </div>
                  <ProgressBar value={value || 0} max={latency.max_ms || 1} color={color} />
                </div>
              ))}
              <p className="text-[9px] text-text-muted text-right mt-2">
                {latency.total_samples.toLocaleString()} samples
              </p>
            </div>
          ) : (
            <p className="text-sm text-text-muted text-center py-8">No latency data yet</p>
          )}
        </Card>

        {/* Error Breakdown */}
        <Card className="p-5">
          <h4 className="text-xs font-semibold text-text-primary mb-4 flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-warning" />
            HTTP Error Breakdown
          </h4>
          {totalStatusCounted > 0 ? (
            <div className="space-y-2">
              {Object.entries(statusCodes)
                .sort((a, b) => b[1] - a[1])
                .map(([code, count]) => {
                  const pct = totalStatusCounted > 0 ? ((count / totalStatusCounted) * 100).toFixed(1) : 0;
                  const codeColor = code.startsWith('4') ? 'warning' : 'danger';
                  return (
                    <div key={code} className="flex items-center gap-3 py-1.5">
                      <span className={`text-xs font-mono font-bold text-${codeColor} w-8`}>{code}</span>
                      <div className="flex-1">
                        <ProgressBar value={count} max={totalStatusCounted} color={codeColor} height="h-5" />
                      </div>
                      <span className="text-xs text-text-muted w-12 text-right">{count}</span>
                      <span className="text-[10px] text-text-muted w-10 text-right">{pct}%</span>
                    </div>
                  );
                })}
              <p className="text-[9px] text-text-muted text-right mt-2">
                {totalStatusCounted} total errors
              </p>
            </div>
          ) : (
            <div className="text-center py-8">
              <CheckCircle2 className="w-8 h-8 text-cta/30 mx-auto mb-2" />
              <p className="text-sm text-text-muted">No errors recorded</p>
              <p className="text-[10px] text-text-muted mt-1">All requests returned 2xx</p>
            </div>
          )}
        </Card>
      </div>

      {/* Top Endpoints Table */}
      <Card className="p-5">
        <h4 className="text-xs font-semibold text-text-primary mb-4 flex items-center gap-2">
          <Server className="w-3.5 h-3.5 text-cta" />
          Endpoint Performance
          <span className="text-[10px] text-text-muted font-normal ml-auto">
            Top {topEndpoints.length} by traffic
          </span>
        </h4>
        {topEndpoints.length > 0 ? (
          <div className="space-y-1.5 max-h-80 overflow-auto">
            {/* Header */}
            <div className="flex items-center gap-3 py-1 px-2 text-[10px] text-text-muted uppercase tracking-wider">
              <span className="flex-1">Endpoint</span>
              <span className="w-20 text-right">Requests</span>
              <span className="w-16 text-right">Errors</span>
              <span className="w-16 text-right">Err %</span>
              <span className="w-20 text-right">Avg</span>
              <span className="w-20 text-right">P95</span>
            </div>
            {topEndpoints.map((ep, i) => {
              const errPct = ep.requests > 0 ? ((ep.errors / ep.requests) * 100).toFixed(1) : '0.0';
              const isHighErr = parseFloat(errPct) > 5;
              return (
                <div
                  key={i}
                  className="flex items-center gap-3 py-2 px-2 bg-surface rounded-lg hover:bg-secondary/50 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] font-mono px-1 py-0.5 rounded bg-cta/10 text-cta font-bold">
                        {ep.endpoint.split(' ')[0]}
                      </span>
                      <span className="text-xs text-text-primary font-medium truncate font-mono">
                        {ep.endpoint.split(' ').slice(1).join(' ')}
                      </span>
                    </div>
                    {/* Mini bar showing relative request volume */}
                    <div className="mt-1 h-1 bg-surface rounded-full overflow-hidden">
                      <div
                        className="h-full bg-cta/30 rounded-full"
                        style={{ width: `${(ep.requests / maxEndpointRequests) * 100}%` }}
                      />
                    </div>
                  </div>
                  <span className="w-20 text-right text-xs font-bold text-text-primary">
                    {formatNumber(ep.requests)}
                  </span>
                  <span className={`w-16 text-right text-xs ${ep.errors > 0 ? 'text-danger font-bold' : 'text-text-muted'}`}>
                    {ep.errors > 0 ? ep.errors : '—'}
                  </span>
                  <span className={`w-16 text-right text-xs ${isHighErr ? 'text-danger font-bold' : 'text-text-muted'}`}>
                    {ep.errors > 0 ? `${errPct}%` : '—'}
                  </span>
                  <span className="w-20 text-right text-xs text-text-secondary">
                    {ep.avg_ms ? formatMs(ep.avg_ms) : '—'}
                  </span>
                  <span className={`w-20 text-right text-xs ${ep.p95_ms > 5000 ? 'text-danger font-bold' : ep.p95_ms > 2000 ? 'text-warning' : 'text-text-secondary'}`}>
                    {ep.p95_ms ? formatMs(ep.p95_ms) : '—'}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-text-muted text-center py-8">No endpoint data yet</p>
        )}
      </Card>

      {/* System Info Footer */}
      {health && (
        <Card className="p-4">
          <h4 className="text-xs font-semibold text-text-primary mb-3 flex items-center gap-2">
            <Wifi className="w-3.5 h-3.5 text-cta" />
            System Information
          </h4>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {[
              { label: 'Version', value: health.version || 'N/A' },
              { label: 'Environment', value: health.environment || 'N/A' },
              { label: 'OpenAI', value: health.openai_connected ? 'Connected' : 'Disconnected' },
              { label: 'Storage', value: health.storage_configured ? 'Configured' : 'Local' },
              { label: 'AWS Services', value: health.services?.aws || 0 },
              { label: 'Azure Services', value: health.services?.azure || 0 },
              { label: 'GCP Services', value: health.services?.gcp || 0 },
              { label: 'Mappings', value: health.services?.crossCloudMappings || 0 },
            ].map(({ label, value }) => (
              <div key={label} className="bg-surface rounded-lg p-2.5 flex items-center justify-between">
                <span className="text-[10px] text-text-muted">{label}</span>
                <span className="text-xs font-bold text-text-primary">{value}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
