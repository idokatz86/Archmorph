import React, { useState } from 'react';
import { Image, Cloud, Heart, ChevronDown, ChevronUp, Layers, BarChart3, Filter, Search } from 'lucide-react';

const CLOUD_BADGES = {
  AWS: 'bg-amber-500/15 text-amber-400 border-amber-500/20',
  Azure: 'bg-sky-500/15 text-sky-400 border-sky-500/20',
  GCP: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  'On-Prem': 'bg-violet-500/15 text-violet-400 border-violet-500/20',
};

const COMPLEXITY = {
  low: { label: 'Low', color: 'text-emerald-400' },
  medium: { label: 'Medium', color: 'text-amber-400' },
  high: { label: 'High', color: 'text-rose-400' },
};

const SAMPLE_CARDS = [
  { id: 1, title: 'E-Commerce Platform', source: 'AWS', target: 'Azure', services: 14, complexity: 'high', likes: 238, description: 'Full-stack migration of a microservices e-commerce app from ECS to Azure Container Apps, including RDS to Azure SQL and CloudFront to Azure CDN.', tags: ['Containers', 'SQL', 'CDN'] },
  { id: 2, title: 'Data Pipeline', source: 'GCP', target: 'Azure', services: 8, complexity: 'medium', likes: 156, description: 'BigQuery + Dataflow pipeline migrated to Azure Synapse Analytics and Azure Data Factory with equivalent scheduling.', tags: ['Analytics', 'ETL'] },
  { id: 3, title: 'Static SaaS Dashboard', source: 'AWS', target: 'Azure', services: 5, complexity: 'low', likes: 312, description: 'S3 + CloudFront + Lambda@Edge dashboard moved to Azure Static Web Apps with Functions backend.', tags: ['Serverless', 'Static'] },
  { id: 4, title: 'IoT Fleet Manager', source: 'AWS', target: 'GCP', services: 11, complexity: 'high', likes: 89, description: 'AWS IoT Core + Kinesis + DynamoDB fleet management migrated to GCP IoT Core, Pub/Sub, and Firestore.', tags: ['IoT', 'Streaming'] },
  { id: 5, title: 'ML Training Cluster', source: 'On-Prem', target: 'Azure', services: 7, complexity: 'medium', likes: 174, description: 'GPU cluster workloads containerized and moved to Azure Machine Learning with spot instances for cost savings.', tags: ['ML', 'GPU', 'Containers'] },
  { id: 6, title: 'WordPress Multi-Site', source: 'On-Prem', target: 'AWS', services: 4, complexity: 'low', likes: 421, description: 'Legacy LAMP stack WordPress installation migrated to AWS Lightsail with RDS MySQL and S3 media storage.', tags: ['CMS', 'LAMP'] },
];

const CLOUDS = ['All', 'AWS', 'Azure', 'GCP', 'On-Prem'];

export default function MigrationGallery() {
  const [cards] = useState(SAMPLE_CARDS);
  const [sourceFilter, setSourceFilter] = useState('All');
  const [targetFilter, setTargetFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedId, setExpandedId] = useState(null);

  const filtered = cards.filter(c => {
    if (sourceFilter !== 'All' && c.source !== sourceFilter) return false;
    if (targetFilter !== 'All' && c.target !== targetFilter) return false;
    if (searchTerm && !c.title.toLowerCase().includes(searchTerm.toLowerCase())) return false;
    return true;
  });

  const totalLikes = cards.reduce((sum, c) => sum + c.likes, 0);
  const avgServices = cards.length > 0 ? Math.round(cards.reduce((sum, c) => sum + c.services, 0) / cards.length) : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-cta/15 flex items-center justify-center">
          <Image className="w-5 h-5 text-cta" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-text-primary">Migration Gallery</h2>
          <p className="text-xs text-text-muted">Community migration architectures</p>
        </div>
      </div>

      {/* Stats Banner */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Architectures', value: cards.length, icon: Layers },
          { label: 'Avg Services', value: avgServices, icon: BarChart3 },
          { label: 'Total Likes', value: totalLikes.toLocaleString(), icon: Heart },
        ].map(stat => (
          <div key={stat.label} className="bg-secondary rounded-xl p-4 border border-border text-center">
            <stat.icon className="w-5 h-5 text-cta mx-auto mb-1.5" />
            <p className="text-xl font-bold text-text-primary">{stat.value}</p>
            <p className="text-xs text-text-muted">{stat.label}</p>
          </div>
        ))}
      </div>

      {/* Filter Bar */}
      <div className="bg-secondary rounded-xl p-4 border border-border space-y-3">
        <div className="flex items-center gap-2 text-xs font-medium text-text-muted uppercase tracking-wider">
          <Filter className="w-3.5 h-3.5" /> Filters
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {/* Search */}
          <div className="relative flex-1 min-w-[180px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none" />
            <input
              type="text"
              placeholder="Search architectures…"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:ring-1 focus:ring-cta"
            />
          </div>
          {/* Source cloud */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-text-muted">From:</span>
            <div className="flex gap-1">
              {CLOUDS.map(c => (
                <button
                  key={`src-${c}`}
                  onClick={() => setSourceFilter(c)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                    sourceFilter === c ? 'bg-cta text-surface' : 'bg-surface text-text-muted hover:text-text-primary'
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
          {/* Target cloud */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-text-muted">To:</span>
            <div className="flex gap-1">
              {CLOUDS.map(c => (
                <button
                  key={`tgt-${c}`}
                  onClick={() => setTargetFilter(c)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                    targetFilter === c ? 'bg-cta text-surface' : 'bg-surface text-text-muted hover:text-text-primary'
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Gallery Grid */}
      {filtered.length === 0 ? (
        <div className="text-center py-12 text-text-muted">
          <Image className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No architectures match your filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(card => {
            const cx = COMPLEXITY[card.complexity];
            const expanded = expandedId === card.id;
            return (
              <div
                key={card.id}
                className="bg-secondary rounded-xl border border-border overflow-hidden hover:border-cta/30 transition-colors"
              >
                <div className="p-4 space-y-3">
                  {/* Cloud badges */}
                  <div className="flex items-center gap-2">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${CLOUD_BADGES[card.source]}`}>
                      <Cloud className="w-3 h-3" /> {card.source}
                    </span>
                    <span className="text-text-muted text-xs">→</span>
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border ${CLOUD_BADGES[card.target]}`}>
                      <Cloud className="w-3 h-3" /> {card.target}
                    </span>
                  </div>

                  {/* Title */}
                  <h3 className="text-sm font-semibold text-text-primary">{card.title}</h3>

                  {/* Meta row */}
                  <div className="flex items-center gap-4 text-xs text-text-muted">
                    <span className="flex items-center gap-1"><Layers className="w-3 h-3" /> {card.services} services</span>
                    <span className={`font-medium ${cx.color}`}>{cx.label} complexity</span>
                    <span className="flex items-center gap-1 ml-auto"><Heart className="w-3 h-3" /> {card.likes}</span>
                  </div>

                  {/* Tags */}
                  <div className="flex flex-wrap gap-1.5">
                    {card.tags.map(tag => (
                      <span key={tag} className="px-2 py-0.5 rounded-md bg-surface text-[11px] text-text-muted font-medium">
                        {tag}
                      </span>
                    ))}
                  </div>

                  {/* Expand */}
                  <button
                    onClick={() => setExpandedId(expanded ? null : card.id)}
                    className="flex items-center gap-1 text-xs text-cta hover:text-cta/80 transition-colors cursor-pointer"
                    aria-expanded={expanded}
                  >
                    {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                    {expanded ? 'Less details' : 'More details'}
                  </button>

                  {expanded && (
                    <p className="text-xs text-text-muted leading-relaxed border-t border-border pt-3">
                      {card.description}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
