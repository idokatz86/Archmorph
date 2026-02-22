/**
 * AI Mapping Suggestion panel (#153).
 *
 * Provides AI-powered cross-cloud service mapping suggestions,
 * batch analysis, dependency graph visualization, and admin review queue.
 */

import React, { useState, useCallback } from 'react';
import {
  Sparkles, Search, Loader2, AlertTriangle, CheckCircle2, XCircle, RefreshCw,
  GitBranch, ArrowRight, ChevronDown, ChevronUp, ThumbsUp, ThumbsDown, ListFilter,
} from 'lucide-react';
import { Card, Badge, Button } from './ui';
import api from '../services/apiClient';

function ConfidenceMeter({ confidence }) {
  const pct = Math.round(confidence * 100);
  const color = pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-500';
  const textColor = pct >= 80 ? 'text-green-400' : pct >= 50 ? 'text-yellow-400' : 'text-red-400';

  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full bg-border overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs font-mono ${textColor}`}>{pct}%</span>
    </div>
  );
}

function SuggestionCard({ suggestion }) {
  const [open, setOpen] = useState(false);

  return (
    <Card className="p-4">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <Badge variant="aws">{suggestion.source_service}</Badge>
          <ArrowRight className="w-4 h-4 text-text-muted shrink-0" />
          <Badge variant="azure">{suggestion.azure_service}</Badge>
        </div>
        <ConfidenceMeter confidence={suggestion.confidence} />
        {suggestion.rationale && (
          <button onClick={() => setOpen(!open)} className="text-text-muted hover:text-text-primary cursor-pointer">
            {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        )}
      </div>
      {suggestion.source === 'gpt' && (
        <div className="mt-1.5 flex items-center gap-1">
          <Sparkles className="w-3 h-3 text-amber-400" />
          <span className="text-xs text-amber-400">AI-generated</span>
        </div>
      )}
      {open && suggestion.rationale && (
        <p className="mt-2 pt-2 border-t border-border text-xs text-text-muted">{suggestion.rationale}</p>
      )}
    </Card>
  );
}

function SingleSuggest() {
  const [service, setService] = useState('');
  const [provider, setProvider] = useState('aws');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSuggest = async (e) => {
    e.preventDefault();
    if (!service.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.post('/suggest/mapping', { source_service: service, source_provider: provider });
      setResult(data);
    } catch (err) {
      setError(err.message || 'Suggestion failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="p-5">
      <h4 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-2 mb-3">
        <Search className="w-4 h-4" /> Single Service Lookup
      </h4>
      <form onSubmit={handleSuggest} className="flex items-end gap-2 mb-3">
        <div className="flex-1">
          <label className="block text-xs text-text-muted mb-1">Service name</label>
          <input
            type="text"
            value={service}
            onChange={(e) => setService(e.target.value)}
            placeholder="e.g. Amazon SQS, Cloud Pub/Sub"
            className="w-full px-3 py-2 text-sm bg-surface border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-cta/50 text-text-primary placeholder:text-text-muted"
          />
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1">Provider</label>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="px-3 py-2 text-sm bg-surface border border-border rounded-lg text-text-primary cursor-pointer"
          >
            <option value="aws">AWS</option>
            <option value="gcp">GCP</option>
          </select>
        </div>
        <Button type="submit" loading={loading} icon={Sparkles} size="md">Suggest</Button>
      </form>

      {error && (
        <div className="flex items-center gap-2 text-sm text-danger">
          <AlertTriangle className="w-4 h-4" /> {error}
        </div>
      )}

      {result && <SuggestionCard suggestion={result} />}
    </Card>
  );
}

function DependencyGraph({ diagramId }) {
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchGraph = useCallback(async () => {
    if (!diagramId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.get(`/diagrams/${diagramId}/dependency-graph`);
      setGraph(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [diagramId]);

  if (!diagramId) return null;

  if (!graph && !loading) {
    return (
      <Card className="p-5">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-2">
            <GitBranch className="w-4 h-4" /> Dependency Graph
          </h4>
          <Button onClick={fetchGraph} variant="ghost" size="sm" icon={GitBranch}>Generate</Button>
        </div>
      </Card>
    );
  }

  if (loading) {
    return (
      <Card className="p-5 flex items-center justify-center gap-2">
        <Loader2 className="w-4 h-4 text-cta animate-spin" />
        <span className="text-sm text-text-muted">Building dependency graph…</span>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="p-5 text-center">
        <AlertTriangle className="w-6 h-6 text-danger mx-auto mb-2" />
        <p className="text-sm text-danger">{error}</p>
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-2">
          <GitBranch className="w-4 h-4" /> Dependency Graph
        </h4>
        <Button onClick={fetchGraph} variant="ghost" size="sm" icon={RefreshCw}>Refresh</Button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mb-3">
        {graph.nodes?.map((node, i) => (
          <div key={i} className="px-3 py-2 rounded-lg bg-secondary/50 border border-border text-xs">
            <span className="font-medium text-text-primary">{node.service || node}</span>
          </div>
        ))}
      </div>
      {graph.edges?.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-text-muted font-semibold">Connections ({graph.edges.length})</p>
          {graph.edges.map((edge, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-text-secondary">
              <span>{edge.from}</span>
              <ArrowRight className="w-3 h-3 text-text-muted" />
              <span>{edge.to}</span>
              {edge.type && <Badge>{edge.type}</Badge>}
            </div>
          ))}
        </div>
      )}
      {graph.missing_dependencies?.length > 0 && (
        <div className="mt-3 p-2 rounded-lg bg-warning/10 border border-warning/20">
          <p className="text-xs font-semibold text-warning mb-1">Missing Dependencies</p>
          <div className="flex flex-wrap gap-1">
            {graph.missing_dependencies.map((dep, i) => (
              <Badge key={i} variant="medium">{dep}</Badge>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

export default function AISuggestionPanel({ diagramId }) {
  return (
    <div className="space-y-5">
      <Card className="p-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-500/15 flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-text-primary">AI Mapping Suggestions</h3>
            <p className="text-sm text-text-muted">GPT-4o-powered cross-cloud service mapping with confidence scoring.</p>
          </div>
        </div>
      </Card>

      <SingleSuggest />
      <DependencyGraph diagramId={diagramId} />
    </div>
  );
}
