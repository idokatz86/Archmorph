import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  Boxes,
  CheckCircle2,
  ClipboardCheck,
  Filter,
  Globe2,
  Layers,
  Network,
  Search,
  Shield,
} from 'lucide-react';
import api from '../services/apiClient';
import useAppStore from '../stores/useAppStore';
import { Badge, Button, Card, ErrorCard, Skeleton } from './ui';

const CATEGORY_ICONS = {
  web: Globe2,
  containers: Boxes,
  enterprise: Shield,
};

const DIFFICULTY_VARIANTS = {
  beginner: 'high',
  intermediate: 'medium',
  advanced: 'low',
};

function TemplateSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {Array.from({ length: 6 }).map((_, index) => (
        <Card key={index} className="p-5">
          <Skeleton className="h-5 w-2/3 mb-4" />
          <Skeleton className="h-4 w-full mb-2" />
          <Skeleton className="h-4 w-5/6 mb-5" />
          <div className="flex gap-2">
            <Skeleton className="h-6 w-16" />
            <Skeleton className="h-6 w-20" />
          </div>
        </Card>
      ))}
    </div>
  );
}

function TemplateCard({ template, onUse, loading }) {
  const CategoryIcon = CATEGORY_ICONS[template.category] || Network;
  const deliverables = template.available_deliverables || [];
  const expectedOutputs = template.expected_outputs || [];
  const complexity = template.complexity || template.difficulty;

  return (
    <Card className="p-5 flex flex-col min-h-[22rem]" hover>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg bg-cta/10 border border-cta/20 flex items-center justify-center shrink-0">
          <CategoryIcon className="w-5 h-5 text-cta" aria-hidden="true" />
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 shrink-0">
          <Badge variant={template.source_provider}>{template.source_provider.toUpperCase()}</Badge>
          <Badge variant={DIFFICULTY_VARIANTS[complexity] || 'default'}>{complexity}</Badge>
        </div>
      </div>

      <div className="min-w-0 flex-1">
        <h2 className="text-base font-semibold text-text-primary leading-snug">{template.title}</h2>
        <p className="text-sm text-text-secondary mt-2 leading-relaxed">{template.description}</p>

        {expectedOutputs.length > 0 && (
          <div className="mt-4 space-y-1.5" aria-label={`${template.title} expected outputs`}>
            {expectedOutputs.slice(0, 3).map(output => (
              <div key={output} className="flex items-start gap-2 text-xs text-text-muted leading-relaxed">
                <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 text-cta shrink-0" aria-hidden="true" />
                <span>{output}</span>
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-1.5">
          {template.services.slice(0, 6).map(service => (
            <span key={service} className="px-2 py-1 rounded-md bg-secondary text-[11px] text-text-secondary border border-border">
              {service}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-5 pt-4 border-t border-border space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
          <span className="inline-flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-cta" aria-hidden="true" />
            {template.services.length} services
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-info" aria-hidden="true" />
            {deliverables.length} deliverables
          </span>
          {template.regression_profile && (
            <span className="inline-flex items-center gap-1.5">
              <ClipboardCheck className="w-3.5 h-3.5 text-warning" aria-hidden="true" />
              regression-ready
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5" aria-label={`${template.title} available deliverables`}>
          {deliverables.slice(0, 5).map(deliverable => (
            <span key={deliverable} className="px-2 py-1 rounded-md bg-surface text-[11px] text-text-secondary border border-border">
              {deliverable}
            </span>
          ))}
        </div>
        <div className="flex justify-end">
          <Button size="sm" icon={Layers} loading={loading} onClick={() => onUse(template)}>
            Open in Workbench
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default function TemplateGallery() {
  const setActiveTab = useAppStore(s => s.setActiveTab);
  const setPendingTemplateAnalysis = useAppStore(s => s.setPendingTemplateAnalysis);
  const [templates, setTemplates] = useState([]);
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState('all');
  const [provider, setProvider] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [usingId, setUsingId] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (category !== 'all') params.set('category', category);
    if (provider) params.set('source_provider', provider);
    api.get(`/templates${params.toString() ? `?${params.toString()}` : ''}`, controller.signal)
      .then(data => {
        if (!active) return;
        setTemplates(data.templates || []);
        setCategories(data.categories || []);
      })
      .catch(err => {
        if (active && err.name !== 'AbortError') setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [category, provider]);

  const filteredTemplates = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return templates;
    return templates.filter(template => [
      template.title,
      template.description,
      template.category,
      template.source_provider,
      ...(template.services || []),
      ...(template.tags || []),
      ...(template.available_deliverables || []),
      ...(template.expected_outputs || []),
    ].some(value => String(value).toLowerCase().includes(normalized)));
  }, [query, templates]);

  const handleUseTemplate = async (template) => {
    setUsingId(template.id);
    setError(null);
    try {
      const analysis = await api.post(`/templates/${template.id}/analyze`);
      setPendingTemplateAnalysis(analysis);
      setActiveTab('translator');
    } catch (err) {
      setError(err.message);
    } finally {
      setUsingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Layers className="w-5 h-5 text-cta" aria-hidden="true" />
            <h1 className="text-2xl font-bold text-text-primary">Starter Architectures</h1>
          </div>
          <p className="text-sm text-text-secondary max-w-2xl">
            Open curated AWS and GCP examples in the Workbench, with canonical outputs that double as regression coverage.
          </p>
        </div>

        <div className="flex flex-col sm:flex-row gap-2 lg:justify-end">
          <label className="relative min-w-[16rem]">
            <span className="sr-only">Search starter architectures</span>
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" aria-hidden="true" />
            <input
              value={query}
              onChange={event => setQuery(event.target.value)}
              className="w-full h-9 pl-9 pr-3 text-sm bg-secondary border border-border rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-cta/50 focus:border-cta"
              placeholder="Search starters"
            />
          </label>
          <select
            value={provider}
            onChange={event => setProvider(event.target.value)}
            className="h-9 px-3 text-sm bg-secondary border border-border rounded-lg text-text-primary focus:outline-none focus:ring-2 focus:ring-cta/50 focus:border-cta"
            aria-label="Filter by source provider"
          >
            <option value="">All providers</option>
            <option value="aws">AWS</option>
            <option value="gcp">GCP</option>
          </select>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2" aria-label="Starter architecture categories">
        <Filter className="w-4 h-4 text-text-muted" aria-hidden="true" />
        {categories.map(item => (
          <button
            key={item.id}
            onClick={() => setCategory(item.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
              category === item.id
                ? 'bg-cta/15 text-cta border-cta/30'
                : 'bg-secondary text-text-secondary border-border hover:text-text-primary hover:border-border-light'
            }`}
          >
            {item.label} ({item.count})
          </button>
        ))}
      </div>

      {error && <ErrorCard message={error} onRetry={() => setCategory('all')} />}
      {loading ? (
        <TemplateSkeleton />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredTemplates.map(template => (
            <TemplateCard
              key={template.id}
              template={template}
              onUse={handleUseTemplate}
              loading={usingId === template.id}
            />
          ))}
        </div>
      )}

      {!loading && filteredTemplates.length === 0 && (
        <Card className="p-8 text-center">
          <Activity className="w-8 h-8 text-text-muted mx-auto mb-3" aria-hidden="true" />
          <h2 className="text-base font-semibold text-text-primary">No starter architectures found</h2>
          <p className="text-sm text-text-muted mt-1">Adjust the category, provider, or search term.</p>
        </Card>
      )}
    </div>
  );
}