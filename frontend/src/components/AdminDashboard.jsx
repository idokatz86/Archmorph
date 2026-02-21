import React, { useState, useEffect } from 'react';
import {
  Shield, X, Filter, Activity, BarChart3, AlertTriangle, TrendingUp,
  Zap, Eye, Loader2,
} from 'lucide-react';
import { Badge, Button, Card } from './ui';
import { API_BASE, ADMIN_KEY } from '../constants';

const STEP_COLORS = ['#22C55E', '#3B82F6', '#A855F7', '#F59E0B', '#EF4444', '#06B6D4'];

export default function AdminDashboard({ onClose }) {
  const [funnel, setFunnel] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [daily, setDaily] = useState([]);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);

  const adminHeaders = ADMIN_KEY ? { 'X-Admin-Key': ADMIN_KEY } : {};

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/admin/metrics/funnel`, { headers: adminHeaders }).then(r => r.json()),
      fetch(`${API_BASE}/admin/metrics`, { headers: adminHeaders }).then(r => r.json()),
      fetch(`${API_BASE}/admin/metrics/daily?days=14`, { headers: adminHeaders }).then(r => r.json()),
      fetch(`${API_BASE}/admin/metrics/recent?limit=30`, { headers: adminHeaders }).then(r => r.json()),
    ]).then(([f, m, d, r]) => {
      setFunnel(f);
      setMetrics(m);
      setDaily(d.data || []);
      setRecent(r.events || []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="fixed inset-0 z-[100] bg-surface flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-cta animate-spin" />
    </div>
  );

  const maxFunnel = funnel?.funnel?.[0]?.count || 1;
  const maxDaily = Math.max(...daily.map(d => d.total), 1);

  return (
    <div className="fixed inset-0 z-[100] bg-surface overflow-y-auto">
      <div className="sticky top-0 z-10 bg-surface/90 backdrop-blur-xl border-b border-border">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-danger/15 flex items-center justify-center">
              <Shield className="w-5 h-5 text-danger" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-text-primary">Admin Analytics</h1>
              <p className="text-[10px] text-text-muted uppercase tracking-wider">Archmorph Internal</p>
            </div>
          </div>
          <Button variant="ghost" size="sm" icon={X} onClick={onClose}>Close</Button>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-8 space-y-8">
        {/* Summary Row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Sessions', value: funnel?.total_sessions || 0, icon: Activity, color: 'cta' },
            { label: 'Completion Rate', value: `${funnel?.completion_rate || 0}%`, icon: TrendingUp, color: 'cta' },
            { label: 'Bottleneck', value: funnel?.bottleneck || 'None', icon: AlertTriangle, color: 'warning' },
            { label: 'Events Today', value: metrics?.today?.events || 0, icon: Zap, color: 'cta' },
          ].map(s => (
            <Card key={s.label} className="p-4">
              <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-lg bg-${s.color}/10 flex items-center justify-center`}>
                  <s.icon className={`w-5 h-5 text-${s.color}`} />
                </div>
                <div>
                  <p className="text-xl font-bold text-text-primary truncate">{s.value}</p>
                  <p className="text-xs text-text-muted">{s.label}</p>
                </div>
              </div>
            </Card>
          ))}
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
      </div>
    </div>
  );
}
