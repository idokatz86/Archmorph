import React, { useState, useEffect, useCallback } from 'react';
import {
  Shield, X, Filter, Activity, BarChart3, AlertTriangle, TrendingUp,
  Zap, Eye, Loader2, DollarSign, LogIn, LogOut, Lock, KeyRound,
  Server, ToggleLeft, ToggleRight, Clock, Gauge, ShieldAlert,
} from 'lucide-react';
import { Badge, Button, Card } from './ui';
import api from '../services/apiClient';
import useFocusTrap from '../hooks/useFocusTrap';

const STEP_COLORS = ['#22C55E', '#3B82F6', '#A855F7', '#F59E0B', '#EF4444', '#06B6D4'];
const TABS = [
  { key: 'analytics', label: 'Analytics', icon: BarChart3 },
  { key: 'health', label: 'Health', icon: Server },
  { key: 'flags', label: 'Flags', icon: ToggleRight },
];

const FEATURE_FLAG_ORDER = [
  'deploy_engine',
  'live_cloud_scanner',
  'enterprise_sso_scim',
  'new_ai_model',
  'roadmap_v2',
  'export_pptx',
  'dark_mode',
];

const formatFlagName = (name) => name.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase());

export default function AdminDashboard({ onClose }) {
  const [activeTab, setActiveTab] = useState('analytics');
  const [funnel, setFunnel] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [daily, setDaily] = useState([]);
  const [recent, setRecent] = useState([]);
  const [costs, setCosts] = useState(null);
  const [monitoring, setMonitoring] = useState(null);
  const [releaseStatus, setReleaseStatus] = useState(null);
  const [auditSummary, setAuditSummary] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [flags, setFlags] = useState({});
  const [flagUpdating, setFlagUpdating] = useState(null);
  const [loading, setLoading] = useState(false);
  const trapRef = useFocusTrap();  // Focus trap (#104 — F-010)

  // ── Auth state (memory-only — never persisted) ──
  const [sessionToken, setSessionToken] = useState(null);
  const [loginKey, setLoginKey] = useState('');
  const [loginError, setLoginError] = useState(null);
  const [loginLoading, setLoginLoading] = useState(false);

  // ── Login handler ──
  const handleLogin = async (e) => {
    e.preventDefault();
    setLoginLoading(true);
    setLoginError(null);
    try {
      const data = await api.post('/admin/login', { key: loginKey });
      setSessionToken(data.token);
      setLoginKey(''); // clear from memory immediately
    } catch (err) {
      if (err.status === 503) {
        setLoginError('Admin API not configured on server');
      } else {
        setLoginError(err.rawMessage || 'Invalid admin key');
      }
    } finally {
      setLoginLoading(false);
    }
  };

  // ── Logout handler ──
  const handleLogout = async () => {
    if (sessionToken) {
      api.auth('POST', '/admin/logout', { token: sessionToken }).catch(() => {}); // fire-and-forget
    }
    setSessionToken(null);
    setFunnel(null);
    setMetrics(null);
    setDaily([]);
    setRecent([]);
    setCosts(null);
    setMonitoring(null);
    setReleaseStatus(null);
    setAuditSummary(null);
    setAuditLogs([]);
    setFlags({});
  };

  const refreshAdminData = useCallback((token, signal) => {
    return Promise.all([
      api.auth('GET', '/admin/metrics/funnel', { token, signal }).catch(() => null),
      api.auth('GET', '/admin/metrics/daily?days=14', { token, signal }).catch(() => null),
      api.auth('GET', '/admin/metrics/recent?limit=30', { token, signal }).catch(() => null),
      api.auth('GET', '/admin/costs', { token, signal }).catch(() => null),
      api.auth('GET', '/admin/monitoring', { token, signal }).catch(() => null),
      api.auth('GET', '/admin/release-status', { token, signal }).catch(() => null),
      api.auth('GET', '/admin/audit/summary', { token, signal }).catch(() => null),
      api.auth('GET', '/admin/audit?limit=20', { token, signal }).catch(() => null),
      api.get('/flags', signal).catch(() => null),
    ]).then(([f, d, r, c, mon, release, audit, logs, flagData]) => {
      setFunnel(f);
      setDaily(d?.data || []);
      setRecent(r?.events || []);
      setCosts(c);
      setMonitoring(mon);
      setReleaseStatus(release);
      setAuditSummary(audit);
      setAuditLogs(logs?.logs || []);
      setFlags(flagData?.flags || {});
    });
  }, []);

  const toggleFlag = async (name) => {
    const current = flags[name];
    if (!current || !sessionToken) return;
    const riskyFlags = new Set(['deploy_engine', 'live_cloud_scanner', 'enterprise_sso_scim']);
    if (!current.enabled && riskyFlags.has(name)) {
      const ok = window.confirm(`Enable ${formatFlagName(name)}? Confirm that tenant credentials, rollback, and customer-facing preview copy are ready.`);
      if (!ok) return;
    }
    setFlagUpdating(name);
    try {
      const updated = await api.auth('PATCH', `/flags/${name}`, {
        token: sessionToken,
        body: { enabled: !current.enabled },
      });
      setFlags(prev => ({ ...prev, [name]: updated }));
      const logs = await api.auth('GET', '/admin/audit?limit=20', { token: sessionToken }).catch(() => null);
      setAuditLogs(logs?.logs || []);
    } finally {
      setFlagUpdating(null);
    }
  };

  // ── Fetch dashboard data once authenticated ──
  useEffect(() => {
    if (!sessionToken) return;
    const controller = new AbortController();
    setLoading(true);

    // Validate token with a single request first to avoid 5 parallel 401s
    api.auth('GET', '/admin/metrics', { token: sessionToken, signal: controller.signal })
      .then(m => {
        if (m === null || m === undefined) return;
        setMetrics(m);
        return refreshAdminData(sessionToken, controller.signal).then(() => setLoading(false));
      })
      .catch(err => {
        if (err.status === 401) setSessionToken(null);
        setLoading(false);
      });
    return () => controller.abort();
  }, [sessionToken, refreshAdminData]);

  // Close on Escape key (#104 — F-009)
  useEffect(() => {
    const handleKeyDown = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // ── Login screen ──
  if (!sessionToken) {
    return (
      <div ref={trapRef} className="fixed inset-0 z-[100] bg-surface flex items-center justify-center">
        <div className="absolute top-4 right-4">
          <Button variant="ghost" size="sm" icon={X} onClick={onClose}>Close</Button>
        </div>
        <Card className="w-full max-w-sm p-8">
          <div className="text-center mb-6">
            <div className="w-14 h-14 rounded-xl bg-danger/15 flex items-center justify-center mx-auto mb-4">
              <Lock className="w-7 h-7 text-danger" />
            </div>
            <h2 className="text-lg font-bold text-text-primary">Admin Login</h2>
            <p className="text-xs text-text-muted mt-1">Enter admin key to access the dashboard</p>
          </div>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="relative">
              <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
              <input
                type="password"
                value={loginKey}
                onChange={(e) => setLoginKey(e.target.value)}
                placeholder="Admin key"
                autoFocus
                autoComplete="off"
                className="w-full pl-10 pr-4 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-cta/40 focus:border-cta transition-colors"
              />
            </div>
            {loginError && (
              <div className="flex items-center gap-2 px-3 py-2 bg-danger/10 rounded-lg">
                <AlertTriangle className="w-3.5 h-3.5 text-danger shrink-0" />
                <span className="text-xs text-danger">{loginError}</span>
              </div>
            )}
            <button
              type="submit"
              disabled={!loginKey || loginLoading}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-cta text-surface rounded-lg text-sm font-medium hover:bg-cta/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loginLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <LogIn className="w-4 h-4" />
              )}
              {loginLoading ? 'Authenticating...' : 'Sign In'}
            </button>
          </form>
        </Card>
      </div>
    );
  }

  if (loading) return (
    <div className="fixed inset-0 z-[100] bg-surface flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-cta animate-spin" />
    </div>
  );

  const maxFunnel = funnel?.funnel?.[0]?.count || 1;
  const maxDaily = Math.max(...daily.map(d => d.total), 1);

  return (
    <div ref={trapRef} className="fixed inset-0 z-[100] bg-surface overflow-y-auto">
      <div className="sticky top-0 z-10 bg-surface/90 backdrop-blur-xl border-b border-border">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-danger/15 flex items-center justify-center">
              <Shield className="w-5 h-5 text-danger" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-text-primary">Admin Dashboard</h1>
              <p className="text-[10px] text-text-muted uppercase tracking-wider">Archmorph Internal</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {/* Tab Navigation */}
            <div className="flex items-center bg-secondary rounded-lg p-0.5">
              {TABS.map(tab => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${
                    activeTab === tab.key
                      ? 'bg-cta text-surface shadow-sm'
                      : 'text-text-muted hover:text-text-primary'
                  }`}
                >
                  <tab.icon className="w-3.5 h-3.5" />
                  {tab.label}
                </button>
              ))}
            </div>
            <button
              onClick={handleLogout}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-text-muted hover:text-danger rounded-lg hover:bg-danger/10 transition-colors"
              title="Sign out"
            >
              <LogOut className="w-3.5 h-3.5" />
              Sign Out
            </button>
            <Button variant="ghost" size="sm" icon={X} onClick={onClose}>Close</Button>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-8 space-y-8">
        {/* Analytics Tab */}
        {activeTab === 'analytics' && (<>
        {/* Summary Row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Sessions', value: funnel?.total_sessions || 0, icon: Activity, color: 'cta' },
            { label: 'Completion Rate', value: `${funnel?.completion_rate || 0}%`, icon: TrendingUp, color: 'cta' },
            { label: 'Bottleneck', value: funnel?.bottleneck || 'None', icon: AlertTriangle, color: 'warning' },
            { label: 'Events Today', value: metrics?.today?.events || 0, icon: Zap, color: 'cta' },
          ].map(s => {
            const colorMap = {
              cta: 'bg-cta/10 text-cta',
              warning: 'bg-warning/10 text-warning',
              danger: 'bg-danger/10 text-danger',
              info: 'bg-info/10 text-info',
            };
            const [bgClass, textClass] = (colorMap[s.color] || colorMap.cta).split(' ');
            return (
            <Card key={s.label} className="p-4">
              <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-lg ${bgClass} flex items-center justify-center`}>
                  <s.icon className={`w-5 h-5 ${textClass}`} />
                </div>
                <div>
                  <p className="text-xl font-bold text-text-primary truncate">{s.value}</p>
                  <p className="text-xs text-text-muted">{s.label}</p>
                </div>
              </div>
            </Card>
          );
          })}
        </div>

        {/* Conversion Funnel */}
        <Card className="p-6">
          <h3 className="text-sm font-semibold text-text-primary mb-6 flex items-center gap-2">
            <Filter className="w-4 h-4 text-cta" />
            User Conversion Funnel
          </h3>
          <div className="space-y-3">
            {(funnel?.funnel || []).map((step, i) => {
              const pct = step.pct_of_total ?? (maxFunnel > 0 ? (step.count / maxFunnel * 100) : 0);
              return (
                <div key={step.step}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center text-surface" style={{ backgroundColor: STEP_COLORS[i] }}>
                        {i + 1}
                      </span>
                      <span className="text-sm font-medium text-text-primary">{step.label}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-bold text-text-primary">{step.count}</span>
                      {i > 0 && (
                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                          step.conversion_rate >= 70 ? 'bg-cta/15 text-cta' :
                          step.conversion_rate >= 40 ? 'bg-warning/15 text-warning' :
                          'bg-danger/15 text-danger'
                        }`}>
                          {step.conversion_rate}%
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="h-8 bg-surface rounded-lg overflow-hidden">
                    <div
                      className="h-full rounded-lg transition-all duration-500"
                      style={{ width: `${Math.max(pct, 1)}%`, backgroundColor: STEP_COLORS[i], opacity: 0.8 }}
                    />
                  </div>
                  {i > 0 && step.drop_off > 0 && (
                    <p className="text-[10px] text-text-muted mt-0.5 ml-7">
                      {step.drop_off} user{step.drop_off !== 1 ? 's' : ''} dropped off
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </Card>

        {/* Two-column: Daily Activity + Event Counters */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="p-6">
            <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-cta" />
              Daily Activity (14 Days)
            </h3>
            <div className="flex items-end gap-1 h-36">
              {daily.map(d => (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group">
                  <span className="text-[9px] text-text-muted opacity-0 group-hover:opacity-100 transition-opacity">{d.total}</span>
                  <div
                    className="w-full bg-cta/20 hover:bg-cta/40 rounded-t transition-colors"
                    style={{ height: `${Math.max((d.total / maxDaily) * 100, 3)}%` }}
                    title={`${d.date}: ${d.total} events`}
                  />
                  <span className="text-[8px] text-text-muted truncate w-full text-center">{d.date.slice(5)}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card className="p-6">
            <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
              <Activity className="w-4 h-4 text-cta" />
              All-Time Counters
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(metrics?.totals || {}).filter(([, v]) => v > 0).map(([key, val]) => (
                <div key={key} className="bg-surface rounded-lg p-2.5 flex items-center justify-between">
                  <span className="text-[11px] text-text-muted truncate">{key.replace(/_/g, ' ')}</span>
                  <span className="text-sm font-bold text-text-primary ml-2">{val}</span>
                </div>
              ))}
              {Object.values(metrics?.totals || {}).every(v => v === 0) && (
                <p className="text-sm text-text-muted col-span-2 text-center py-4">No data yet</p>
              )}
            </div>
          </Card>
        </div>

        {/* Recent Sessions */}
        <Card className="p-6">
          <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
            <Eye className="w-4 h-4 text-cta" />
            Recent Sessions
          </h3>
          {(funnel?.recent_sessions || []).length === 0 ? (
            <p className="text-sm text-text-muted text-center py-6">No sessions recorded yet</p>
          ) : (
            <div className="space-y-2 max-h-72 overflow-auto">
              {(funnel?.recent_sessions || []).map((sess, i) => (
                <div key={i} className="flex items-center gap-3 py-2.5 px-3 bg-surface rounded-lg">
                  <div className={`w-2 h-2 rounded-full shrink-0 ${sess.completed ? 'bg-cta' : 'bg-warning'}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-primary font-medium truncate">{sess.session_id}</p>
                    <p className="text-[10px] text-text-muted">
                      Reached: <span className="text-text-secondary">{sess.farthest_step}</span>
                      {' '}&middot;{' '}
                      {sess.steps_completed} step{sess.steps_completed !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    {sess.completed ? (
                      <Badge variant="high">Completed</Badge>
                    ) : (
                      <Badge variant="medium">Dropped</Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Cost Dashboard */}
        {costs && (
          <Card className="p-6">
            <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
              <DollarSign className="w-4 h-4 text-cta" />
              Platform Cost Estimate
              <span className="text-xs text-text-muted font-normal ml-auto">${costs.total_monthly_usd}/mo</span>
            </h3>
            <div className="space-y-2">
              {(costs.resources || []).map((r, i) => (
                <div key={i} className="flex items-center gap-3 py-2 px-3 bg-surface rounded-lg">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-primary font-medium truncate">{r.name}</p>
                    <p className="text-[10px] text-text-muted">{r.notes}</p>
                  </div>
                  <span className="text-sm font-bold text-text-primary shrink-0">
                    ${r.monthly_usd.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
            {costs.usage_based && (
              <div className="mt-4 pt-4 border-t border-border">
                <p className="text-xs text-text-muted mb-2">Token Usage (cumulative)</p>
                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-surface rounded-lg p-2.5 flex items-center justify-between">
                    <span className="text-[11px] text-text-muted">Input tokens</span>
                    <span className="text-sm font-bold text-text-primary">{costs.usage_based.estimated_input_tokens?.toLocaleString()}</span>
                  </div>
                  <div className="bg-surface rounded-lg p-2.5 flex items-center justify-between">
                    <span className="text-[11px] text-text-muted">Output tokens</span>
                    <span className="text-sm font-bold text-text-primary">{costs.usage_based.estimated_output_tokens?.toLocaleString()}</span>
                  </div>
                </div>
              </div>
            )}
          </Card>
        )}

        {/* Recent Events Feed */}
        <Card className="p-6">
          <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
            <Zap className="w-4 h-4 text-cta" />
            Recent Events
          </h3>
          {recent.length === 0 ? (
            <p className="text-sm text-text-muted text-center py-4">No recent events</p>
          ) : (
            <div className="space-y-1.5 max-h-56 overflow-auto">
              {recent.map((evt, i) => (
                <div key={i} className="flex items-center gap-3 py-1.5 text-sm">
                  <span className="w-2 h-2 rounded-full bg-cta/40 shrink-0" />
                  <span className="text-text-primary flex-1 truncate">{evt.type.replace(/_/g, ' ')}</span>
                  <span className="text-xs text-text-muted shrink-0">{new Date(evt.timestamp).toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
        </>)}

        {activeTab === 'health' && (<>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Requests', value: monitoring?.overview?.total_requests || 0, icon: Activity, color: 'cta' },
              { label: 'Error Rate', value: `${monitoring?.overview?.error_rate_pct || 0}%`, icon: ShieldAlert, color: (monitoring?.overview?.error_rate_pct || 0) > 2 ? 'danger' : 'cta' },
              { label: 'P95 Latency', value: `${monitoring?.latency?.p95_ms || 0}ms`, icon: Gauge, color: 'info' },
              { label: 'Uptime', value: monitoring?.overview?.uptime || '0h 0m', icon: Clock, color: 'cta' },
            ].map(s => {
              const colorMap = {
                cta: 'bg-cta/10 text-cta',
                danger: 'bg-danger/10 text-danger',
                info: 'bg-info/10 text-info',
              };
              const [bgClass, textClass] = (colorMap[s.color] || colorMap.cta).split(' ');
              return (
                <Card key={s.label} className="p-4">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-lg ${bgClass} flex items-center justify-center`}>
                      <s.icon className={`w-5 h-5 ${textClass}`} />
                    </div>
                    <div className="min-w-0">
                      <p className="text-xl font-bold text-text-primary truncate">{s.value}</p>
                      <p className="text-xs text-text-muted">{s.label}</p>
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card className="p-6">
              <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
                <Server className="w-4 h-4 text-cta" />
                Top Endpoints
              </h3>
              <div className="space-y-2 max-h-80 overflow-auto">
                {(monitoring?.top_endpoints || []).slice(0, 10).map(endpoint => (
                  <div key={endpoint.endpoint} className="flex items-center gap-3 py-2 px-3 bg-surface rounded-lg">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-text-primary truncate">{endpoint.endpoint}</p>
                      <p className="text-[10px] text-text-muted">{endpoint.errors || 0} errors</p>
                    </div>
                    <span className="text-xs font-semibold text-text-primary">{endpoint.requests} req</span>
                  </div>
                ))}
                {(monitoring?.top_endpoints || []).length === 0 && (
                  <p className="text-sm text-text-muted text-center py-6">No endpoint telemetry yet</p>
                )}
              </div>
            </Card>

            <Card className="p-6">
              <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
                <Shield className="w-4 h-4 text-cta" />
                Audit Summary
              </h3>
              <div className="grid grid-cols-2 gap-2 mb-4">
                <div className="bg-surface rounded-lg p-3">
                  <p className="text-[11px] text-text-muted">Events</p>
                  <p className="text-lg font-bold text-text-primary">{auditSummary?.total_events || 0}</p>
                </div>
                <div className="bg-surface rounded-lg p-3">
                  <p className="text-[11px] text-text-muted">Alerts</p>
                  <p className="text-lg font-bold text-text-primary">{auditSummary?.total_alerts || 0}</p>
                </div>
              </div>
              <div className="space-y-1.5 max-h-56 overflow-auto">
                {auditLogs.map((event, idx) => (
                  <div key={`${event.timestamp}-${idx}`} className="flex items-center gap-2 py-1.5 text-sm">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${event.severity === 'warning' ? 'bg-warning' : event.severity === 'error' ? 'bg-danger' : 'bg-cta/50'}`} />
                    <span className="text-text-primary flex-1 truncate">{event.details?.action || event.event_type}</span>
                    <span className="text-[10px] text-text-muted shrink-0">{new Date(event.timestamp).toLocaleString()}</span>
                  </div>
                ))}
                {auditLogs.length === 0 && (
                  <p className="text-sm text-text-muted text-center py-4">No audit events yet</p>
                )}
              </div>
            </Card>

            <Card className="p-6">
              <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-cta" />
                Release Gate
              </h3>
              <div className="grid grid-cols-2 gap-2 mb-4">
                <div className="bg-surface rounded-lg p-3">
                  <p className="text-[11px] text-text-muted">Version</p>
                  <p className="text-sm font-bold text-text-primary truncate">{releaseStatus?.version || 'unknown'}</p>
                </div>
                <div className="bg-surface rounded-lg p-3">
                  <p className="text-[11px] text-text-muted">Environment</p>
                  <p className="text-sm font-bold text-text-primary truncate">{releaseStatus?.environment || 'unknown'}</p>
                </div>
              </div>
              <div className="space-y-2">
                {(releaseStatus?.smoke_checks || []).map(check => (
                  <div key={check.name} className="flex items-center justify-between py-2 px-3 bg-surface rounded-lg">
                    <span className="text-sm text-text-primary">{check.name}</span>
                    <Badge variant="medium">{check.status}</Badge>
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-text-muted mt-4">
                SHA: {releaseStatus?.git_sha || 'unknown'}
              </p>
            </Card>
          </div>
        </>)}

        {activeTab === 'flags' && (
          <Card className="p-6">
            <h3 className="text-sm font-semibold text-text-primary mb-4 flex items-center gap-2">
              <ToggleRight className="w-4 h-4 text-cta" />
              Runtime Feature Gates
            </h3>
            <div className="space-y-2">
              {FEATURE_FLAG_ORDER.filter(name => flags[name]).map(name => {
                const flag = flags[name];
                const enabled = Boolean(flag.enabled);
                return (
                  <div key={name} className="flex items-center gap-4 py-3 px-4 bg-surface rounded-lg">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-text-primary">{formatFlagName(name)}</p>
                      <p className="text-xs text-text-muted truncate">{flag.description}</p>
                      <p className="text-[10px] text-text-muted mt-1">Rollout {flag.rollout_percentage}%</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => toggleFlag(name)}
                      disabled={flagUpdating === name}
                      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 ${enabled ? 'bg-cta/15 text-cta hover:bg-cta/20' : 'bg-secondary text-text-muted hover:text-text-primary'}`}
                    >
                      {flagUpdating === name ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : enabled ? <ToggleRight className="w-3.5 h-3.5" /> : <ToggleLeft className="w-3.5 h-3.5" />}
                      {enabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </div>
                );
              })}
              {Object.keys(flags).length === 0 && (
                <p className="text-sm text-text-muted text-center py-6">No feature flags available</p>
              )}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
