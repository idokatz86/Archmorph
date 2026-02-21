import React, { useState, useEffect, useMemo } from 'react';
import {
  Calendar, Rocket, Clock, Lightbulb, CheckCircle2, Loader2, ChevronDown, ChevronRight,
  Bug, Sparkles, Send, ExternalLink, GitBranch, Filter, Search, Code, Server, Layers,
} from 'lucide-react';
import { API_BASE } from '../constants';

const STATUS_CONFIG = {
  released: { label: 'Released', color: 'bg-cta', textColor: 'text-cta', icon: CheckCircle2 },
  in_progress: { label: 'In Progress', color: 'bg-warning', textColor: 'text-warning', icon: Loader2 },
  planned: { label: 'Planned', color: 'bg-text-muted', textColor: 'text-text-secondary', icon: Clock },
  idea: { label: 'Under Consideration', color: 'bg-purple-500', textColor: 'text-purple-400', icon: Lightbulb },
};

function ReleaseCard({ release, isExpanded, onToggle }) {
  const config = STATUS_CONFIG[release.status] || STATUS_CONFIG.idea;
  const Icon = config.icon;
  const isInProgress = release.status === 'in_progress';

  return (
    <div 
      className={`relative border rounded-xl transition-all duration-200 ${
        isInProgress 
          ? 'border-warning/50 bg-warning/5 shadow-lg shadow-warning/10' 
          : 'border-border bg-secondary/50 hover:border-border/80'
      }`}
    >
      <button
        onClick={onToggle}
        className="w-full text-left px-4 py-4 flex items-start gap-4 cursor-pointer"
      >
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${
          isInProgress ? 'bg-warning/20' : 'bg-primary'
        }`}>
          <Icon className={`w-5 h-5 ${isInProgress ? 'text-warning animate-pulse' : config.textColor}`} />
        </div>
        
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-2 py-0.5 rounded-md text-xs font-mono ${
              isInProgress ? 'bg-warning/20 text-warning' : 'bg-primary text-cta'
            }`}>
              {release.version}
            </span>
            <h3 className="text-base font-semibold text-text-primary truncate">{release.name}</h3>
          </div>
          
          <div className="flex items-center gap-3 mt-1">
            {release.date && (
              <span className="flex items-center gap-1 text-xs text-text-muted">
                <Calendar className="w-3 h-3" />
                {new Date(release.date).toLocaleDateString('en-US', { 
                  year: 'numeric', month: 'short', day: 'numeric' 
                })}
              </span>
            )}
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${config.color}/20 ${config.textColor}`}>
              {config.label}
            </span>
          </div>
        </div>

        <div className="shrink-0 text-text-muted">
          {isExpanded ? <ChevronDown className="w-5 h-5" /> : <ChevronRight className="w-5 h-5" />}
        </div>
      </button>

      {isExpanded && (
        <div className="px-4 pb-4 pt-0">
          <div className="pl-14 border-t border-border/50 pt-3">
            <ul className="space-y-2">
              {release.highlights?.map((feature, idx) => (
                <li key={idx} className="flex items-start gap-2 text-sm text-text-secondary">
                  <Sparkles className="w-3.5 h-3.5 text-cta shrink-0 mt-0.5" />
                  <span>{feature}</span>
                </li>
              ))}
            </ul>
            
            {release.metrics && (
              <div className="flex items-center gap-4 mt-4 pt-3 border-t border-border/50">
                {release.metrics.services && (
                  <div className="flex items-center gap-1.5 text-xs text-text-muted">
                    <Server className="w-3.5 h-3.5" />
                    <span>{release.metrics.services} services</span>
                  </div>
                )}
                {release.metrics.mappings && (
                  <div className="flex items-center gap-1.5 text-xs text-text-muted">
                    <Layers className="w-3.5 h-3.5" />
                    <span>{release.metrics.mappings} mappings</span>
                  </div>
                )}
                {release.metrics.api_endpoints && (
                  <div className="flex items-center gap-1.5 text-xs text-text-muted">
                    <Code className="w-3.5 h-3.5" />
                    <span>{release.metrics.api_endpoints} API endpoints</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function FeatureRequestModal({ onClose, onSubmit, loading }) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [useCase, setUseCase] = useState('');
  const [email, setEmail] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({ title, description, use_case: useCase, email: email || undefined });
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-primary border border-border rounded-2xl w-full max-w-lg shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-border flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-cta/15 flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-cta" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Request a Feature</h2>
            <p className="text-xs text-text-muted">Your request will be added to our backlog</p>
          </div>
        </div>
        
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">Feature Title *</label>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="e.g., Add Kubernetes manifest generation"
              required
              minLength={5}
              maxLength={200}
              className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">Description *</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Describe the feature you'd like to see..."
              required
              minLength={20}
              maxLength={2000}
              rows={4}
              className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 resize-none"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">Use Case (optional)</label>
            <textarea
              value={useCase}
              onChange={e => setUseCase(e.target.value)}
              placeholder="How would you use this feature?"
              maxLength={1000}
              rows={2}
              className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 resize-none"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">Email (optional)</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="your@email.com for follow-up"
              className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50"
            />
          </div>
          
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!title.trim() || !description.trim() || loading}
              className="flex items-center gap-2 px-4 py-2 bg-cta hover:bg-cta-hover text-surface text-sm font-semibold rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              Submit Request
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function BugReportModal({ onClose, onSubmit, loading }) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [steps, setSteps] = useState('');
  const [expected, setExpected] = useState('');
  const [actual, setActual] = useState('');
  const [email, setEmail] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({
      title,
      description,
      steps_to_reproduce: steps || undefined,
      expected_behavior: expected || undefined,
      actual_behavior: actual || undefined,
      browser: navigator.userAgent,
      os_info: navigator.platform,
      email: email || undefined,
    });
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-primary border border-border rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-border flex items-center gap-3 sticky top-0 bg-primary">
          <div className="w-10 h-10 rounded-lg bg-error/15 flex items-center justify-center">
            <Bug className="w-5 h-5 text-error" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Report a Bug</h2>
            <p className="text-xs text-text-muted">Help us improve by reporting issues</p>
          </div>
        </div>
        
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">Bug Title *</label>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="Brief summary of the issue"
              required
              minLength={5}
              maxLength={200}
              className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">Description *</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Detailed description of what went wrong..."
              required
              minLength={20}
              maxLength={2000}
              rows={3}
              className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 resize-none"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">Steps to Reproduce</label>
            <textarea
              value={steps}
              onChange={e => setSteps(e.target.value)}
              placeholder="1. Go to...\n2. Click on...\n3. See error"
              rows={3}
              className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 resize-none font-mono text-xs"
            />
          </div>
          
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">Expected Behavior</label>
              <input
                type="text"
                value={expected}
                onChange={e => setExpected(e.target.value)}
                placeholder="What should happen"
                className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1.5">Actual Behavior</label>
              <input
                type="text"
                value={actual}
                onChange={e => setActual(e.target.value)}
                placeholder="What actually happens"
                className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50"
              />
            </div>
          </div>
          
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">Email (optional)</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="your@email.com for follow-up"
              className="w-full px-3 py-2.5 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50"
            />
          </div>
          
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!title.trim() || !description.trim() || loading}
              className="flex items-center gap-2 px-4 py-2 bg-error hover:bg-error/80 text-white text-sm font-semibold rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bug className="w-4 h-4" />}
              Submit Bug Report
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function SuccessToast({ message, issueUrl, onClose }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 5000);
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-cta text-surface px-4 py-3 rounded-xl shadow-lg shadow-cta/30 flex items-center gap-3 animate-slide-up">
      <CheckCircle2 className="w-5 h-5" />
      <span className="text-sm font-medium">{message}</span>
      {issueUrl && (
        <a 
          href={issueUrl} 
          target="_blank" 
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-sm font-semibold underline cursor-pointer"
        >
          View Issue <ExternalLink className="w-3.5 h-3.5" />
        </a>
      )}
    </div>
  );
}

export default function Roadmap() {
  const [roadmap, setRoadmap] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedVersions, setExpandedVersions] = useState(new Set());
  const [filter, setFilter] = useState('all');
  const [featureModalOpen, setFeatureModalOpen] = useState(false);
  const [bugModalOpen, setBugModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/roadmap`)
      .then(r => r.json())
      .then(data => {
        setRoadmap(data);
        // Auto-expand in-progress versions
        const inProgress = data.timeline?.in_progress?.map(r => r.version) || [];
        setExpandedVersions(new Set(inProgress));
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const toggleExpanded = (version) => {
    setExpandedVersions(prev => {
      const next = new Set(prev);
      if (next.has(version)) {
        next.delete(version);
      } else {
        next.add(version);
      }
      return next;
    });
  };

  const filteredReleases = useMemo(() => {
    if (!roadmap) return { sections: [] };
    const { released = [], in_progress = [], planned = [], ideas = [] } = roadmap.timeline || {};
    
    // Group releases by status for better UX
    const sortedReleased = [...released].sort((a, b) => {
      // Sort by version number descending (newest first)
      const vA = a.version.replace('v', '').split('.').map(Number);
      const vB = b.version.replace('v', '').split('.').map(Number);
      for (let i = 0; i < 3; i++) {
        if ((vB[i] || 0) !== (vA[i] || 0)) return (vB[i] || 0) - (vA[i] || 0);
      }
      return 0;
    });

    switch (filter) {
      case 'released':
        return {
          sections: [
            { title: 'Released', status: 'released', items: sortedReleased, icon: CheckCircle2 }
          ]
        };
      case 'planned':
        return {
          sections: [
            { title: 'Planned for Future', status: 'planned', items: planned, icon: Clock }
          ]
        };
      case 'ideas':
        return {
          sections: [
            { title: 'Under Consideration', status: 'idea', items: ideas, icon: Lightbulb }
          ]
        };
      default:
        return {
          sections: [
            { title: 'In Progress', status: 'in_progress', items: in_progress, icon: Loader2, highlight: true },
            { title: 'Recently Released', status: 'released', items: sortedReleased.slice(0, 5), icon: CheckCircle2 },
            { title: 'Coming Soon', status: 'planned', items: planned, icon: Clock },
            { title: 'Ideas & Requests', status: 'idea', items: ideas, icon: Lightbulb },
          ].filter(s => s.items.length > 0)
        };
    }
  }, [roadmap, filter]);

  const handleFeatureSubmit = async (data) => {
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/roadmap/feature-request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const result = await res.json();
      if (result.success) {
        setToast({ message: 'Feature request submitted!', issueUrl: result.issue_url });
        setFeatureModalOpen(false);
      } else {
        setError(result.error || 'Failed to submit request');
      }
    } catch (err) {
      setError('Failed to connect to server');
    }
    setSubmitting(false);
  };

  const handleBugSubmit = async (data) => {
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/roadmap/bug-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const result = await res.json();
      if (result.success) {
        setToast({ message: 'Bug report submitted!', issueUrl: result.issue_url });
        setBugModalOpen(false);
      } else {
        setError(result.error || 'Failed to submit bug report');
      }
    } catch (err) {
      setError('Failed to connect to server');
    }
    setSubmitting(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-8 h-8 text-cta animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-20">
        <p className="text-error mb-4">Failed to load roadmap: {error}</p>
        <button 
          onClick={() => window.location.reload()} 
          className="px-4 py-2 bg-cta text-surface rounded-lg cursor-pointer"
        >
          Retry
        </button>
      </div>
    );
  }

  const { stats } = roadmap || {};

  return (
    <div className="space-y-8">
      {/* Header & Stats */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
        <div>
          <h1 className="text-2xl font-bold text-text-primary flex items-center gap-3">
            <Rocket className="w-7 h-7 text-cta" />
            Roadmap & Timeline
          </h1>
          <p className="text-text-muted mt-1">
            From Day 0 to today — see what we've built and what's coming next
          </p>
        </div>
        
        <div className="flex items-center gap-3">
          <button
            onClick={() => setFeatureModalOpen(true)}
            className="flex items-center gap-2 px-4 py-2.5 bg-cta hover:bg-cta-hover text-surface text-sm font-semibold rounded-lg transition-colors cursor-pointer"
          >
            <Sparkles className="w-4 h-4" />
            Request Feature
          </button>
          <button
            onClick={() => setBugModalOpen(true)}
            className="flex items-center gap-2 px-4 py-2.5 bg-error/10 hover:bg-error/20 text-error text-sm font-semibold rounded-lg border border-error/30 transition-colors cursor-pointer"
          >
            <Bug className="w-4 h-4" />
            Report Bug
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Releases Shipped', value: stats.total_releases, icon: Rocket },
              { label: 'Features Delivered', value: stats.features_shipped, icon: Sparkles },
              { label: 'Days Since Launch', value: stats.days_since_launch, icon: Calendar },
              { label: 'Current Version', value: stats.current_version, icon: GitBranch },
            ].map((stat, i) => (
              <div key={i} className="bg-secondary/50 border border-border rounded-xl px-4 py-3">
                <div className="flex items-center gap-2 text-text-muted mb-1">
                  <stat.icon className="w-4 h-4" />
                  <span className="text-xs font-medium">{stat.label}</span>
                </div>
                <p className="text-xl font-bold text-text-primary">{stat.value}</p>
              </div>
            ))}
          </div>

          {/* Productivity Progress Bar */}
          {stats.progress_pct !== undefined && (
            <div className="bg-secondary/50 border border-border rounded-xl px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-text-muted">
                  Team Productivity — {stats.releases_remaining} release{stats.releases_remaining !== 1 ? 's' : ''} remaining
                </span>
                <span className="text-xs font-bold text-cta">{stats.progress_pct}% complete</span>
              </div>
              <div className="w-full bg-primary rounded-full h-2">
                <div
                  className="bg-cta h-2 rounded-full transition-all duration-500"
                  style={{ width: `${stats.progress_pct}%` }}
                />
              </div>
              {stats.velocity !== undefined && (
                <p className="text-xs text-text-muted mt-1.5">
                  Shipping at <span className="font-semibold text-text-secondary">{stats.velocity} releases/week</span>
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-2 border-b border-border pb-4">
        <Filter className="w-4 h-4 text-text-muted" />
        {[
          { id: 'all', label: 'All' },
          { id: 'released', label: 'Released' },
          { id: 'planned', label: 'Planned' },
          { id: 'ideas', label: 'Ideas' },
        ].map(f => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors cursor-pointer ${
              filter === f.id 
                ? 'bg-cta/15 text-cta' 
                : 'text-text-secondary hover:text-text-primary hover:bg-secondary'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Timeline by Sections */}
      <div className="space-y-8">
        {filteredReleases.sections.map((section, sIdx) => (
          <div key={section.title} className="space-y-3">
            {/* Section Header */}
            <div className={`flex items-center gap-3 pb-2 border-b ${
              section.highlight ? 'border-warning/30' : 'border-border/50'
            }`}>
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                section.highlight ? 'bg-warning/20' : 'bg-secondary'
              }`}>
                <section.icon className={`w-4 h-4 ${
                  section.highlight ? 'text-warning animate-pulse' : 
                  section.status === 'released' ? 'text-cta' :
                  section.status === 'planned' ? 'text-text-muted' :
                  'text-purple-400'
                }`} />
              </div>
              <h2 className={`text-lg font-semibold ${
                section.highlight ? 'text-warning' : 'text-text-primary'
              }`}>
                {section.title}
              </h2>
              <span className="text-xs text-text-muted bg-secondary px-2 py-0.5 rounded-full">
                {section.items.length}
              </span>
            </div>

            {/* Release Cards */}
            <div className="space-y-2 pl-4 border-l-2 border-border/30 ml-4">
              {section.items.map((release, idx) => (
                <ReleaseCard
                  key={release.version + idx}
                  release={release}
                  isExpanded={expandedVersions.has(release.version)}
                  onToggle={() => toggleExpanded(release.version)}
                />
              ))}
            </div>

            {/* Show more link for Released section in All view */}
            {section.status === 'released' && filter === 'all' && roadmap.timeline.released.length > 5 && (
              <button
                onClick={() => setFilter('released')}
                className="ml-8 text-sm text-cta hover:underline cursor-pointer"
              >
                View all {roadmap.timeline.released.length} releases →
              </button>
            )}
          </div>
        ))}

        {filteredReleases.sections.length === 0 && (
          <div className="text-center py-12 text-text-muted">
            <p>No items in this category yet.</p>
          </div>
        )}
      </div>

      {/* GitHub Link */}
      <div className="text-center py-8 border-t border-border">
        <p className="text-text-muted text-sm mb-3">
          Want to contribute or see the full development history?
        </p>
        <a
          href="https://github.com/idokatz86/Archmorph"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-border text-text-primary text-sm font-medium rounded-lg transition-colors cursor-pointer"
        >
          <GitBranch className="w-4 h-4" />
          View on GitHub
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      </div>

      {/* Modals */}
      {featureModalOpen && (
        <FeatureRequestModal
          onClose={() => setFeatureModalOpen(false)}
          onSubmit={handleFeatureSubmit}
          loading={submitting}
        />
      )}
      
      {bugModalOpen && (
        <BugReportModal
          onClose={() => setBugModalOpen(false)}
          onSubmit={handleBugSubmit}
          loading={submitting}
        />
      )}

      {/* Toast */}
      {toast && (
        <SuccessToast
          message={toast.message}
          issueUrl={toast.issueUrl}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
}
