import React, { useState, useEffect, useCallback } from 'react';
import {
  LayoutDashboard, FileSearch, Download, BarChart3, Clock, Bookmark,
  BookmarkCheck, ChevronRight, RefreshCw, Loader2, AlertTriangle,
  Code, FileText, ArrowUpRight, Filter, TrendingUp,
} from 'lucide-react';
import { Card, Button, Badge } from './ui';
import api from '../services/apiClient';

const PROVIDER_COLORS = {
  aws: { bg: 'bg-[#FF9900]/15', text: 'text-[#FF9900]', label: 'AWS' },
  gcp: { bg: 'bg-[#EA4335]/15', text: 'text-[#EA4335]', label: 'GCP' },
  azure: { bg: 'bg-info/15', text: 'text-info', label: 'Azure' },
};

function StatCard({ icon: Icon, label, value, sub, color = 'text-cta' }) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-text-muted uppercase tracking-wider">{label}</p>
          <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
          {sub && <p className="text-xs text-text-muted mt-1">{sub}</p>}
        </div>
        <div className="p-2 bg-secondary rounded-lg">
          <Icon className={`w-5 h-5 ${color}`} />
        </div>
      </div>
    </Card>
  );
}

function AnalysisRow({ analysis, onReanalyze, onToggleSave }) {
  const prov = PROVIDER_COLORS[analysis.source_provider] || PROVIDER_COLORS.aws;
  const tgtProv = PROVIDER_COLORS[analysis.target_provider] || PROVIDER_COLORS.azure;
  const confPct = analysis.confidence_avg != null ? `${Math.round(analysis.confidence_avg * 100)}%` : '—';

  return (
    <div className="flex items-center gap-4 p-4 hover:bg-secondary/50 transition-colors rounded-lg group">
      {/* Provider badges */}
      <div className="flex items-center gap-1.5 min-w-[110px]">
        <span className={`text-xs px-2 py-0.5 rounded-md font-medium ${prov.bg} ${prov.text}`}>{prov.label}</span>
        <ChevronRight className="w-3 h-3 text-text-muted" />
        <span className={`text-xs px-2 py-0.5 rounded-md font-medium ${tgtProv.bg} ${tgtProv.text}`}>{tgtProv.label}</span>
      </div>

      {/* Title + meta */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-text-primary truncate">
          {analysis.title || `Analysis ${analysis.analysis_id.slice(0, 8)}`}
        </p>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-xs text-text-muted flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {new Date(analysis.created_at).toLocaleDateString()}
          </span>
          <span className="text-xs text-text-muted">
            {analysis.services_detected} services · {analysis.mappings_count} mappings
          </span>
          <span className="text-xs text-text-muted">
            Confidence: {confPct}
          </span>
        </div>
      </div>

      {/* Feature badges */}
      <div className="hidden sm:flex items-center gap-1.5">
        {analysis.iac_generated && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-cta/10 text-cta"><Code className="w-3 h-3 inline" /> IaC</span>
        )}
        {analysis.hld_generated && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-info/10 text-info"><FileText className="w-3 h-3 inline" /> HLD</span>
        )}
        {/* Cost badge hidden during beta */}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => onToggleSave(analysis)}
          className="p-1.5 rounded-lg hover:bg-secondary text-text-muted hover:text-cta transition-colors"
          title={analysis.is_saved ? 'Remove bookmark' : 'Bookmark'}
        >
          {analysis.is_saved ? <BookmarkCheck className="w-4 h-4 text-cta" /> : <Bookmark className="w-4 h-4" />}
        </button>
        <button
          onClick={() => onReanalyze(analysis)}
          className="p-1.5 rounded-lg hover:bg-secondary text-text-muted hover:text-cta transition-colors"
          title="Re-analyze"
        >
          <ArrowUpRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

export default function UserDashboard({ onNavigate }) {
  const [stats, setStats] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [filterProvider, setFilterProvider] = useState('');

  const fetchData = useCallback(async (pageNum = 1, append = false) => {
    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams({ page: pageNum, page_size: 20 });
      if (filterProvider) params.set('source_provider', filterProvider);

      const [statsData, listData] = await Promise.all([
        pageNum === 1 ? api.get('/dashboard/stats') : Promise.resolve(null),
        api.get(`/dashboard/analyses?${params}`),
      ]);

      if (statsData) setStats(statsData);
      setAnalyses(prev => append ? [...prev, ...listData.analyses] : listData.analyses);
      setHasMore(listData.has_more);
      setTotal(listData.total);
      setPage(pageNum);
    } catch (err) {
      setError(err.message || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, [filterProvider]);

  useEffect(() => {
    fetchData(1);
  }, [fetchData]);

  const handleToggleSave = async (analysis) => {
    try {
      if (analysis.is_saved) {
        await api.delete(`/dashboard/analyses/${analysis.analysis_id}/save`);
      } else {
        await api.post(`/dashboard/analyses/${analysis.analysis_id}/save`, {});
      }
      setAnalyses(prev =>
        prev.map(a =>
          a.analysis_id === analysis.analysis_id ? { ...a, is_saved: !a.is_saved } : a
        )
      );
    } catch {
      // Silently fail bookmark toggle
    }
  };

  const handleReanalyze = (analysis) => {
    if (onNavigate) onNavigate('translator');
  };

  if (error && !analyses.length) {
    return (
      <div className="text-center py-16">
        <AlertTriangle className="w-12 h-12 text-danger mx-auto mb-4" />
        <p className="text-text-secondary mb-4">{error}</p>
        <Button onClick={() => fetchData(1)} icon={RefreshCw}>Try Again</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
            <LayoutDashboard className="w-6 h-6 text-cta" />
            Dashboard
          </h1>
          <p className="text-sm text-text-muted mt-1">Your analysis history, saved diagrams, and usage metrics</p>
        </div>
        <Button onClick={() => onNavigate?.('translator')} icon={ArrowUpRight} variant="primary" size="sm">
          New Analysis
        </Button>
      </div>

      {/* Stats Grid */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard icon={FileSearch} label="Total Analyses" value={stats.total_analyses} color="text-cta" />
          <StatCard icon={TrendingUp} label="This Month" value={stats.analyses_this_month} color="text-info" />
          <StatCard icon={Code} label="IaC Generated" value={stats.iac_generated} color="text-cta" />
          <StatCard icon={FileText} label="HLD Docs" value={stats.hld_generated} color="text-info" />
          {/* Cost Estimates stat hidden during beta */}
          <StatCard icon={Bookmark} label="Saved" value={stats.saved_diagrams} color="text-cta" />
        </div>
      )}

      {/* Analysis History */}
      <Card className="overflow-hidden">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 className="font-semibold text-text-primary flex items-center gap-2">
            <Clock className="w-4 h-4 text-text-muted" />
            Analysis History
            <span className="text-xs text-text-muted font-normal">({total})</span>
          </h2>
          <div className="flex items-center gap-2">
            <Filter className="w-3.5 h-3.5 text-text-muted" />
            <select
              value={filterProvider}
              onChange={(e) => setFilterProvider(e.target.value)}
              className="text-xs bg-secondary border border-border rounded-lg px-2 py-1 text-text-secondary focus:outline-none focus:ring-1 focus:ring-cta/50"
            >
              <option value="">All Providers</option>
              <option value="aws">AWS</option>
              <option value="gcp">GCP</option>
              <option value="azure">Azure</option>
            </select>
          </div>
        </div>

        {loading && !analyses.length ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="w-6 h-6 text-cta animate-spin" />
            <span className="ml-2 text-sm text-text-muted">Loading history…</span>
          </div>
        ) : analyses.length === 0 ? (
          <div className="text-center py-16">
            <FileSearch className="w-12 h-12 text-text-muted mx-auto mb-4 opacity-50" />
            <p className="text-text-secondary font-medium">No analyses yet</p>
            <p className="text-xs text-text-muted mt-1">Upload a cloud architecture diagram to get started</p>
            <Button onClick={() => onNavigate?.('translator')} className="mt-4" size="sm">
              Start First Analysis
            </Button>
          </div>
        ) : (
          <div className="divide-y divide-border/50">
            {analyses.map((a) => (
              <AnalysisRow
                key={a.analysis_id}
                analysis={a}
                onReanalyze={handleReanalyze}
                onToggleSave={handleToggleSave}
              />
            ))}
          </div>
        )}

        {/* Load More */}
        {hasMore && (
          <div className="p-4 border-t border-border text-center">
            <Button
              onClick={() => fetchData(page + 1, true)}
              variant="ghost"
              size="sm"
              loading={loading}
            >
              Load More
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
