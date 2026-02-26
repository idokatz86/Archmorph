import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Filter, BarChart3, Server, Layers, Box, FileText, Loader2,
  AlertTriangle, RefreshCw,
} from 'lucide-react';
import { Badge, Card } from './ui';
import { getCategoryIcon } from '../constants';
import api from '../services/apiClient';

export default function ServicesBrowser() {
  const [services, setServices] = useState([]);
  const [stats, setStats] = useState(null);
  const [search, setSearch] = useState('');
  const [provider, setProvider] = useState('all');
  const [category, setCategory] = useState('all');
  const [categories, setCategories] = useState([]);
  const [view, setView] = useState('grid');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [visibleCount, setVisibleCount] = useState(60);

  const fetchData = useCallback((signal) => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.get('/services?page_size=1000', signal),
      api.get('/services/stats', signal),
      api.get('/services/categories', signal),
    ]).then(([svc, st, cats]) => {
      setServices(svc.services || []);
      setStats(st);
      setCategories((cats.categories || []).map(c => typeof c === 'string' ? c : c.name));
      setLoading(false);
    }).catch((err) => {
      if (err.name === 'AbortError') return;
      setError(err.message || 'Failed to load services');
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchData(controller.signal);
    return () => controller.abort();
  }, [fetchData]);

  const filtered = services.filter(s => {
    if (provider !== 'all' && s.provider !== provider) return false;
    if (category !== 'all' && s.category !== category) return false;
    if (search && !s.name.toLowerCase().includes(search.toLowerCase()) && !s.description?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="w-8 h-8 text-cta animate-spin" />
    </div>
  );

  if (error) return (
    <Card className="p-8">
      <div className="flex flex-col items-center justify-center gap-4 text-center">
        <AlertTriangle className="w-10 h-10 text-danger" />
        <div>
          <h3 className="text-lg font-semibold text-text-primary mb-1">Failed to load services</h3>
          <p className="text-sm text-text-muted">{error}</p>
        </div>
        <button
          onClick={() => fetchData()}
          className="flex items-center gap-2 px-4 py-2 bg-cta hover:bg-cta-hover text-surface rounded-lg text-sm font-medium transition-colors cursor-pointer"
        >
          <RefreshCw className="w-4 h-4" />
          Try Again
        </button>
      </div>
    </Card>
  );

  return (
    <div className="space-y-6">
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Services', value: stats.totalServices, icon: Server },
            { label: 'Cross-Cloud Mappings', value: stats.totalMappings, icon: Layers },
            { label: 'Categories', value: stats.categories, icon: Filter },
            { label: 'Avg Confidence', value: `${(stats.avgConfidence * 100).toFixed(0)}%`, icon: BarChart3 },
          ].map(s => (
            <Card key={s.label} className="p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-cta/10 flex items-center justify-center">
                  <s.icon className="w-5 h-5 text-cta" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-text-primary">{s.value}</p>
                  <p className="text-xs text-text-muted">{s.label}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Filters */}
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
            <input
              type="text"
              placeholder="Search services..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 focus:ring-1 focus:ring-cta/30 transition-colors"
            />
          </div>
          <select value={provider} onChange={e => setProvider(e.target.value)} className="px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary cursor-pointer focus:outline-none focus:border-cta/50">
            <option value="all">All Providers</option>
            <option value="aws">AWS</option>
            <option value="azure">Azure</option>
            <option value="gcp">GCP</option>
          </select>
          <select value={category} onChange={e => setCategory(e.target.value)} className="px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary cursor-pointer focus:outline-none focus:border-cta/50">
            <option value="all">All Categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <div className="flex items-center gap-1 border border-border rounded-lg p-0.5" role="group" aria-label="View mode">
            {['grid', 'list'].map(v => (
              <button key={v} onClick={() => setView(v)} aria-label={`${v} view`} aria-pressed={view === v} className={`p-1.5 rounded cursor-pointer transition-colors ${view === v ? 'bg-cta/15 text-cta' : 'text-text-muted hover:text-text-primary'}`}>
                {v === 'grid' ? <Box className="w-4 h-4" /> : <FileText className="w-4 h-4" />}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-text-muted">{filtered.length} services found</p>
      </Card>

      {/* Service Grid/List */}
      <div className={view === 'grid' ? 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4' : 'space-y-2'}>
        {filtered.slice(0, visibleCount).map((s, i) => {
          const Icon = getCategoryIcon(s.category);
          return view === 'grid' ? (
            <Card key={i} hover className="p-4">
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-secondary flex items-center justify-center shrink-0">
                  <Icon className="w-4 h-4 text-text-secondary" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-semibold text-text-primary truncate">{s.name}</h3>
                    <Badge variant={s.provider}>{s.provider.toUpperCase()}</Badge>
                  </div>
                  <p className="text-xs text-text-muted line-clamp-2">{s.description}</p>
                  <p className="text-[10px] text-text-muted mt-2 uppercase tracking-wide">{s.category}</p>
                </div>
              </div>
            </Card>
          ) : (
            <Card key={i} hover className="px-4 py-3">
              <div className="flex items-center gap-4">
                <Icon className="w-4 h-4 text-text-muted shrink-0" />
                <span className="text-sm font-medium text-text-primary flex-1 truncate">{s.name}</span>
                <Badge variant={s.provider}>{s.provider.toUpperCase()}</Badge>
                <span className="text-xs text-text-muted hidden md:block truncate max-w-xs">{s.category}</span>
              </div>
            </Card>
          );
        })}
      </div>
      {filtered.length > visibleCount && (
        <div className="text-center space-y-2">
          <p className="text-sm text-text-muted">Showing {visibleCount} of {filtered.length} services</p>
          <button
            onClick={() => setVisibleCount(prev => prev + 60)}
            className="px-4 py-2 bg-secondary hover:bg-secondary/80 border border-border rounded-lg text-sm text-text-primary font-medium transition-colors cursor-pointer"
          >
            Load More
          </button>
        </div>
      )}
    </div>
  );
}
