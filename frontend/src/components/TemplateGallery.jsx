import React, { useState, useEffect } from 'react';
import {
  Boxes, Globe, Zap, Activity, Brain, Shield, Cpu, Workflow, Globe2, Loader2,
  ArrowRight, Tag, Filter, Search, Sparkles, ChevronRight,
} from 'lucide-react';
import { Card, Button, Badge } from './ui';
import api from '../services/apiClient';

const ICON_MAP = {
  globe: Globe,
  globe2: Globe2,
  zap: Zap,
  boxes: Boxes,
  activity: Activity,
  brain: Brain,
  shield: Shield,
  cpu: Cpu,
  workflow: Workflow,
};

const DIFFICULTY_COLORS = {
  beginner: 'bg-emerald-500/15 text-emerald-400',
  intermediate: 'bg-amber-500/15 text-amber-400',
  advanced: 'bg-rose-500/15 text-rose-400',
};

export default function TemplateGallery({ onUseTemplate }) {
  const [templates, setTemplates] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeCategory, setActiveCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const data = await api.get(`/templates?category=${activeCategory}`);
        setTemplates(data.templates || []);
        setCategories(data.categories || []);
      } catch {
        setTemplates([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [activeCategory]);

  const filtered = searchQuery
    ? templates.filter(
        (t) =>
          t.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.tags.some((tag) => tag.includes(searchQuery.toLowerCase()))
      )
    : templates;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <Sparkles className="w-6 h-6 text-cta" />
          Architecture Templates
        </h2>
        <p className="text-sm text-text-muted mt-1">
          Start from proven architecture patterns — click &quot;Use Template&quot; to load into the translator
        </p>
      </div>

      {/* Search + Categories */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            type="text"
            placeholder="Search templates…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-2 bg-secondary border border-border rounded-lg text-sm text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-cta/50"
          />
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {categories.map((cat) => (
            <button
              key={cat.id}
              onClick={() => setActiveCategory(cat.id)}
              className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors cursor-pointer ${
                activeCategory === cat.id
                  ? 'bg-cta/15 text-cta'
                  : 'bg-secondary text-text-muted hover:text-text-secondary'
              }`}
            >
              {cat.label}
              <span className="ml-1 opacity-50">({cat.count})</span>
            </button>
          ))}
        </div>
      </div>

      {/* Template Grid */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 text-cta animate-spin" />
          <span className="ml-2 text-sm text-text-muted">Loading templates…</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16">
          <Filter className="w-12 h-12 text-text-muted mx-auto mb-4 opacity-50" />
          <p className="text-text-secondary font-medium">No templates match your search</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((template) => {
            const IconComp = ICON_MAP[template.icon] || Globe;
            const diffClass = DIFFICULTY_COLORS[template.difficulty] || DIFFICULTY_COLORS.beginner;

            return (
              <Card key={template.id} className="p-0 overflow-hidden hover:border-cta/30 transition-colors group">
                {/* Card Header */}
                <div className="p-4 pb-3">
                  <div className="flex items-start justify-between mb-3">
                    <div className="p-2 bg-cta/10 rounded-lg">
                      <IconComp className="w-5 h-5 text-cta" />
                    </div>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wider ${diffClass}`}>
                      {template.difficulty}
                    </span>
                  </div>
                  <h3 className="font-semibold text-text-primary text-sm">{template.title}</h3>
                  <p className="text-xs text-text-muted mt-1.5 line-clamp-2">{template.description}</p>
                </div>

                {/* Services pills */}
                <div className="px-4 pb-3">
                  <div className="flex flex-wrap gap-1">
                    {template.services.slice(0, 4).map((svc) => (
                      <span key={svc} className="text-[10px] px-1.5 py-0.5 bg-secondary rounded text-text-muted">
                        {svc}
                      </span>
                    ))}
                    {template.services.length > 4 && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-secondary rounded text-text-muted">
                        +{template.services.length - 4}
                      </span>
                    )}
                  </div>
                </div>

                {/* Footer */}
                <div className="px-4 py-3 border-t border-border flex items-center justify-end">
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => onUseTemplate?.(template)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    Use Template
                    <ChevronRight className="w-3 h-3 ml-1" />
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
