import React, { useState, useMemo, useCallback, useRef } from 'react';
import {
  ArrowUpDown, ArrowUp, ArrowDown, Filter, ChevronDown, ChevronUp,
  AlertTriangle, CheckCircle2, ArrowRight, X, LayoutGrid,
} from 'lucide-react';
import { Badge, Card } from '../ui';
import { ContextualHint } from '../ContextualHint';

/* ── Helpers ── */
const effortValue = (e) => e === 'low' ? 1 : e === 'medium' ? 2 : e === 'high' ? 3 : 0;
const effortLabel = (v) => v === 1 ? 'low' : v === 2 ? 'medium' : 'high';

function inferCategory(m) {
  const name = (m.azure_service || '').toLowerCase();
  if (name.includes('sql') || name.includes('cosmos') || name.includes('storage') || name.includes('redis') || name.includes('cache')) return 'Data';
  if (name.includes('function') || name.includes('app service') || name.includes('container') || name.includes('kubernetes') || name.includes('vm')) return 'Compute';
  if (name.includes('vnet') || name.includes('gateway') || name.includes('cdn') || name.includes('front door') || name.includes('load balancer') || name.includes('dns') || name.includes('traffic')) return 'Networking';
  if (name.includes('key vault') || name.includes('firewall') || name.includes('sentinel') || name.includes('defender') || name.includes('identity') || name.includes('entra')) return 'Security';
  if (name.includes('monitor') || name.includes('insight') || name.includes('log')) return 'Monitoring';
  if (name.includes('queue') || name.includes('bus') || name.includes('event') || name.includes('grid')) return 'Messaging';
  return 'Other';
}

function getSourceName(m) {
  if (typeof m.source_service === 'object') return m.source_service.name || m.source_service.source || '';
  return m.source_service || '';
}

function getGaps(m) {
  return (m.limitations || []).filter(l => {
    if (!l) return false;
    const s = typeof l === 'string' ? l : l.factor || '';
    return s.toLowerCase() !== 'none' && s.toLowerCase() !== 'n/a' && s.trim() !== '';
  });
}

function getMigrationEffort(m) {
  // Check migration_notes for effort, or infer from confidence
  const notes = m.migration_notes || [];
  const efforts = notes.map(n => typeof n === 'string' ? null : n.effort).filter(Boolean);
  if (efforts.length > 0) {
    const max = Math.max(...efforts.map(effortValue));
    return effortLabel(max);
  }
  if (m.confidence >= 0.9) return 'low';
  if (m.confidence >= 0.7) return 'medium';
  return 'high';
}

/* ── Summary Bar ── */
function SummaryBar({ mappings }) {
  const total = mappings.length;
  const high = mappings.filter(m => m.confidence >= 0.9).length;
  const med = mappings.filter(m => m.confidence >= 0.7 && m.confidence < 0.9).length;
  const low = mappings.filter(m => m.confidence > 0 && m.confidence < 0.7).length;
  const noMatch = mappings.filter(m => !m.confidence || m.confidence === 0).length;

  const effortLow = mappings.filter(m => getMigrationEffort(m) === 'low').length;
  const effortMed = mappings.filter(m => getMigrationEffort(m) === 'medium').length;
  const effortHigh = mappings.filter(m => getMigrationEffort(m) === 'high').length;

  const gapCount = mappings.filter(m => getGaps(m).length > 0).length;

  const automatable = total > 0 ? Math.round((high / total) * 100) : 0;
  const avgConfidence = total > 0 ? Math.round(mappings.reduce((s, m) => s + (m.confidence || 0), 0) / total * 100) : 0;
  const dominantEffort = effortHigh > effortMed ? 'High' : effortMed > effortLow ? 'Medium' : 'Low';

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {/* Services Mapped */}
      <Card className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-text-muted font-medium">Services Mapped</span>
          <span className="text-2xl font-bold text-text-primary">{total}</span>
        </div>
        <div className="flex gap-1 h-2 rounded-full overflow-hidden bg-secondary">
          {high > 0 && <div className="bg-cta transition-all" style={{ width: `${(high / total) * 100}%` }} title={`${high} high confidence`} />}
          {med > 0 && <div className="bg-warning transition-all" style={{ width: `${(med / total) * 100}%` }} title={`${med} medium confidence`} />}
          {(low + noMatch) > 0 && <div className="bg-danger transition-all" style={{ width: `${((low + noMatch) / total) * 100}%` }} title={`${low + noMatch} low/none`} />}
        </div>
        <p className="text-[10px] text-text-muted mt-1.5">{avgConfidence}% avg confidence</p>
      </Card>

      {/* Migration Effort */}
      <Card className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-text-muted font-medium">Migration Effort</span>
          <span className={`text-lg font-bold ${dominantEffort === 'Low' ? 'text-cta' : dominantEffort === 'Medium' ? 'text-warning' : 'text-danger'}`}>{dominantEffort}</span>
        </div>
        <div className="flex gap-3 text-xs">
          <span className="text-cta font-medium">{effortLow} easy</span>
          <span className="text-warning font-medium">{effortMed} moderate</span>
          <span className="text-danger font-medium">{effortHigh} complex</span>
        </div>
        <p className="text-[10px] text-text-muted mt-1.5">{automatable}% automatable</p>
      </Card>

      {/* Gaps Found */}
      <Card className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-text-muted font-medium">Gaps Found</span>
          <span className={`text-2xl font-bold ${gapCount === 0 ? 'text-cta' : gapCount <= 3 ? 'text-warning' : 'text-danger'}`}>{gapCount}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <AlertTriangle className={`w-3.5 h-3.5 ${gapCount === 0 ? 'text-cta' : 'text-warning'}`} />
          <span className="text-xs text-text-secondary">
            {gapCount === 0 ? 'All services map cleanly' : `${gapCount} service${gapCount > 1 ? 's' : ''} need${gapCount === 1 ? 's' : ''} attention`}
          </span>
        </div>
      </Card>
    </div>
  );
}

/* ── Filter Bar ── */
function FilterBar({ filters, categories, onFilterChange }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs">
      {/* Confidence range */}
      <div className="flex items-center gap-2">
        <Filter className="w-3.5 h-3.5 text-text-muted" />
        <label className="text-text-muted">Confidence:</label>
        <input
          type="range"
          min={0}
          max={100}
          value={filters.minConfidence}
          onChange={(e) => onFilterChange({ ...filters, minConfidence: Number(e.target.value) })}
          className="w-24 accent-cta cursor-pointer"
        />
        <span className="text-text-secondary font-mono w-8">{filters.minConfidence}%</span>
      </div>

      {/* Category chips */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {categories.map(cat => (
          <button
            key={cat}
            onClick={() => {
              const next = filters.categories.includes(cat)
                ? filters.categories.filter(c => c !== cat)
                : [...filters.categories, cat];
              onFilterChange({ ...filters, categories: next });
            }}
            className={`px-2 py-0.5 rounded-full text-[10px] font-medium border transition-colors cursor-pointer ${
              filters.categories.includes(cat)
                ? 'bg-cta/15 text-cta border-cta/30'
                : 'bg-secondary text-text-muted border-border hover:border-border-light'
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Effort dropdown */}
      <select
        value={filters.effort}
        onChange={(e) => onFilterChange({ ...filters, effort: e.target.value })}
        className="text-xs px-2 py-1 rounded-lg bg-secondary border border-border text-text-primary cursor-pointer focus:outline-none focus:ring-1 focus:ring-cta"
      >
        <option value="all">All effort</option>
        <option value="low">Low effort</option>
        <option value="medium">Medium effort</option>
        <option value="high">High effort</option>
      </select>

      {/* Has gaps toggle */}
      <label className="flex items-center gap-1.5 text-text-muted cursor-pointer">
        <input
          type="checkbox"
          checked={filters.hasGaps}
          onChange={(e) => onFilterChange({ ...filters, hasGaps: e.target.checked })}
          className="accent-cta w-3 h-3"
        />
        Has gaps
      </label>

      {/* Clear */}
      {(filters.minConfidence > 0 || filters.categories.length > 0 || filters.effort !== 'all' || filters.hasGaps) && (
        <button
          onClick={() => onFilterChange({ minConfidence: 0, categories: [], effort: 'all', hasGaps: false })}
          className="flex items-center gap-1 text-text-muted hover:text-text-primary cursor-pointer"
        >
          <X className="w-3 h-3" /> Clear
        </button>
      )}
    </div>
  );
}

/* ── Risk Matrix (SVG scatter) ── */
const QUADRANT_LABELS = [
  { x: 85, y: 1.3, label: 'Quick Wins', color: 'text-cta' },
  { x: 85, y: 2.8, label: 'Plan Carefully', color: 'text-warning' },
  { x: 15, y: 1.3, label: 'Review Mapping', color: 'text-info' },
  { x: 15, y: 2.8, label: 'Deep Work', color: 'text-danger' },
];

const CATEGORY_COLORS = {
  Compute: '#3B82F6',
  Data: '#10B981',
  Networking: '#F59E0B',
  Security: '#EF4444',
  Monitoring: '#8B5CF6',
  Messaging: '#EC4899',
  Other: '#6B7280',
};

/* ── Confidence Ring (SVG arc indicator) (#516) ── */
function ConfidenceRing({ value, size = 32 }) {
  const r = (size - 4) / 2;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - value / 100);
  const color = value >= 90 ? '#22C55E' : value >= 70 ? '#F59E0B' : '#EF4444';
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-label={`${value}% confidence`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-secondary)" strokeWidth={3} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={3}
        strokeDasharray={circumference} strokeDashoffset={offset}
        strokeLinecap="round" transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="transition-all duration-700" />
      <text x={size / 2} y={size / 2 + 1} textAnchor="middle" dominantBaseline="middle"
        className="text-[8px] font-bold fill-current text-text-primary">{value}%</text>
    </svg>
  );
}

/* ── Mapping Card (card view mode) (#516) ── */
function MappingCard({ m, sourceProvider, onClick }) {
  return (
    <Card hover className="p-4 cursor-pointer stagger-item" onClick={onClick}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className={`text-xs font-semibold ${sourceProvider === 'gcp' ? 'text-[#EA4335]' : 'text-[#FF9900]'}`}>
              {m._source}
            </span>
            <ArrowRight className="w-3 h-3 text-text-muted shrink-0" />
            <span className="text-xs font-semibold text-info truncate">{m._target}</span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant={m._effort === 'low' ? 'high' : m._effort === 'high' ? 'low' : 'medium'}>
              {m._effort} effort
            </Badge>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-secondary text-text-muted">{m._category}</span>
            {m._gaps.length > 0 && (
              <span className="flex items-center gap-0.5 text-[10px] text-warning">
                <AlertTriangle className="w-3 h-3" />{m._gaps.length} gap{m._gaps.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
        </div>
        <ConfidenceRing value={Math.round(m._confidence)} size={36} />
      </div>
    </Card>
  );
}

function RiskMatrix({ mappings, onDotClick }) {
  const [tooltip, setTooltip] = useState(null);
  const svgRef = useRef(null);

  // Chart dimensions
  const W = 600, H = 300;
  const pad = { top: 30, right: 30, bottom: 40, left: 50 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const dots = mappings.map((m, i) => {
    const conf = (m.confidence || 0) * 100;
    const eff = effortValue(getMigrationEffort(m));
    const cat = inferCategory(m);
    // Map to SVG coords
    const cx = pad.left + (conf / 100) * plotW;
    // Invert Y: low effort at bottom, high at top
    const cy = pad.top + ((eff - 0.5) / 3) * plotH;
    return { i, m, cx, cy, conf, eff, cat, source: getSourceName(m), target: m.azure_service };
  });

  return (
    <Card className="p-4">
      <div className="flex items-center gap-4 mb-3 flex-wrap">
        {Object.entries(CATEGORY_COLORS).map(([cat, color]) => (
          <div key={cat} className="flex items-center gap-1.5 text-[10px] text-text-muted">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            {cat}
          </div>
        ))}
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full max-w-[600px]"
        role="img"
        aria-label="Risk matrix scatter chart"
      >
        {/* Grid */}
        <rect x={pad.left} y={pad.top} width={plotW} height={plotH} fill="none" className="stroke-border" strokeWidth={1} />
        {/* Quadrant dividers */}
        <line x1={pad.left + plotW / 2} y1={pad.top} x2={pad.left + plotW / 2} y2={pad.top + plotH} className="stroke-border" strokeDasharray="4 4" />
        <line x1={pad.left} y1={pad.top + plotH / 2} x2={pad.left + plotW} y2={pad.top + plotH / 2} className="stroke-border" strokeDasharray="4 4" />

        {/* Quadrant labels */}
        {QUADRANT_LABELS.map(q => {
          const x = pad.left + (q.x / 100) * plotW;
          const y = pad.top + ((q.y - 0.5) / 3) * plotH;
          return (
            <text key={q.label} x={x} y={y} textAnchor="middle" className={`text-[10px] fill-current opacity-30 ${q.color}`}>{q.label}</text>
          );
        })}

        {/* X axis label */}
        <text x={pad.left + plotW / 2} y={H - 5} textAnchor="middle" className="text-[11px] fill-current text-text-muted">Confidence %</text>
        {/* X ticks */}
        {[0, 25, 50, 75, 100].map(v => (
          <text key={v} x={pad.left + (v / 100) * plotW} y={pad.top + plotH + 15} textAnchor="middle" className="text-[9px] fill-current text-text-muted">{v}%</text>
        ))}

        {/* Y axis label */}
        <text x={12} y={pad.top + plotH / 2} textAnchor="middle" transform={`rotate(-90, 12, ${pad.top + plotH / 2})`} className="text-[11px] fill-current text-text-muted">Effort</text>
        {/* Y ticks */}
        {[{ v: 1, l: 'Low' }, { v: 2, l: 'Med' }, { v: 3, l: 'High' }].map(({ v, l }) => (
          <text key={v} x={pad.left - 8} y={pad.top + ((v - 0.5) / 3) * plotH + 4} textAnchor="end" className="text-[9px] fill-current text-text-muted">{l}</text>
        ))}

        {/* Dots */}
        {dots.map(d => (
          <circle
            key={d.i}
            cx={d.cx}
            cy={d.cy}
            r={6}
            fill={CATEGORY_COLORS[d.cat] || CATEGORY_COLORS.Other}
            opacity={0.8}
            className="cursor-pointer hover:opacity-100 transition-opacity"
            onMouseEnter={(e) => {
              const rect = svgRef.current?.getBoundingClientRect();
              const svgPoint = { x: d.cx, y: d.cy };
              setTooltip({ x: svgPoint.x, y: svgPoint.y, source: d.source, target: d.target, conf: d.conf, eff: d.eff, rect });
            }}
            onMouseLeave={() => setTooltip(null)}
            onClick={() => onDotClick?.(d.i)}
          />
        ))}
      </svg>

      {/* Tooltip (rendered below SVG for simplicity) */}
      {tooltip && (
        <div className="mt-2 px-3 py-2 bg-secondary border border-border rounded-lg text-xs inline-block">
          <span className="font-medium text-text-primary">{tooltip.source}</span>
          <ArrowRight className="w-3 h-3 text-text-muted inline mx-1" />
          <span className="text-info font-medium">{tooltip.target}</span>
          <span className="text-text-muted ml-2">{tooltip.conf.toFixed(0)}% conf · {effortLabel(tooltip.eff)} effort</span>
        </div>
      )}
    </Card>
  );
}

/* ── Main ResultsTable ── */
export default function ResultsTable({ analysis, activeView, onViewChange }) {
  const mappings = analysis?.mappings || [];

  const [sortCol, setSortCol] = useState(null); // 'source' | 'target' | 'confidence' | 'effort' | 'category' | 'gaps'
  const [sortDir, setSortDir] = useState('asc');
  const [expandedRow, setExpandedRow] = useState(null);
  const [filters, setFilters] = useState({ minConfidence: 0, categories: [], effort: 'all', hasGaps: false });
  const rowRefs = useRef({});

  // Derive categories
  const allCategories = useMemo(() => {
    const cats = new Set(mappings.map(inferCategory));
    return Array.from(cats).sort();
  }, [mappings]);

  // Enrich mappings
  const enriched = useMemo(() => mappings.map((m, i) => ({
    ...m,
    _idx: i,
    _source: getSourceName(m),
    _target: m.azure_service || '',
    _confidence: (m.confidence || 0) * 100,
    _effort: getMigrationEffort(m),
    _category: inferCategory(m),
    _gaps: getGaps(m),
  })), [mappings]);

  // Filter
  const filtered = useMemo(() => {
    return enriched.filter(m => {
      if (m._confidence < filters.minConfidence) return false;
      if (filters.categories.length > 0 && !filters.categories.includes(m._category)) return false;
      if (filters.effort !== 'all' && m._effort !== filters.effort) return false;
      if (filters.hasGaps && m._gaps.length === 0) return false;
      return true;
    });
  }, [enriched, filters]);

  // Sort
  const sorted = useMemo(() => {
    if (!sortCol) return filtered;
    const copy = [...filtered];
    const dir = sortDir === 'asc' ? 1 : -1;
    copy.sort((a, b) => {
      let av, bv;
      switch (sortCol) {
        case 'source': av = a._source; bv = b._source; return dir * av.localeCompare(bv);
        case 'target': av = a._target; bv = b._target; return dir * av.localeCompare(bv);
        case 'confidence': return dir * (a._confidence - b._confidence);
        case 'effort': return dir * (effortValue(a._effort) - effortValue(b._effort));
        case 'category': return dir * a._category.localeCompare(b._category);
        case 'gaps': return dir * (a._gaps.length - b._gaps.length);
        default: return 0;
      }
    });
    return copy;
  }, [filtered, sortCol, sortDir]);

  const handleSort = useCallback((col) => {
    if (sortCol === col) {
      setSortDir(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  }, [sortCol]);

  const handleDotClick = useCallback((idx) => {
    onViewChange?.('table');
    setExpandedRow(idx);
    setTimeout(() => {
      rowRefs.current[idx]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 100);
  }, [onViewChange]);

  const SortIcon = ({ col }) => {
    if (sortCol !== col) return <ArrowUpDown className="w-3 h-3 text-text-muted opacity-40" />;
    return sortDir === 'asc' ? <ArrowUp className="w-3 h-3 text-cta" /> : <ArrowDown className="w-3 h-3 text-cta" />;
  };

  const sourceProvider = analysis?.source_provider;

  return (
    <div className="space-y-4">
      {/* Summary */}
      <ContextualHint id="results-review" content="Review your mappings below, then generate IaC" position="bottom">
        <SummaryBar mappings={mappings} />
      </ContextualHint>

      {/* View Toggle */}
      <div className="flex items-center gap-1 bg-secondary rounded-xl p-1 w-fit">
        {[
          { id: 'card', label: 'Cards' },
          { id: 'table', label: 'Table' },
          { id: 'matrix', label: 'Matrix' },
          { id: 'map', label: 'Map' },
        ].map(v => (
          <button
            key={v.id}
            onClick={() => onViewChange?.(v.id)}
            className={`px-4 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
              activeView === v.id ? 'bg-cta/15 text-cta shadow-sm' : 'text-text-muted hover:text-text-primary'
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* Matrix View */}
      {activeView === 'matrix' && (
        <RiskMatrix mappings={mappings} onDotClick={handleDotClick} />
      )}

      {/* Card View (#516) */}
      {activeView === 'card' && (
        <>
          <details className="group">
            <summary className="flex items-center gap-2 text-xs text-text-muted cursor-pointer hover:text-text-primary mb-2">
              <Filter className="w-3.5 h-3.5" /> Filters
              <ChevronDown className="w-3 h-3 group-open:rotate-180 transition-transform" />
            </summary>
            <div className="mb-3">
              <FilterBar filters={filters} categories={allCategories} onFilterChange={setFilters} />
            </div>
          </details>

          {allCategories.map(cat => {
            const catItems = sorted.filter(m => m._category === cat);
            if (catItems.length === 0) return null;
            return (
              <details key={cat} open className="group/cat mb-3">
                <summary className="flex items-center gap-2 cursor-pointer mb-2">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: CATEGORY_COLORS[cat] || CATEGORY_COLORS.Other }} />
                  <span className="text-sm font-semibold text-text-primary">{cat}</span>
                  <span className="text-xs text-text-muted">({catItems.length})</span>
                  <ChevronDown className="w-3.5 h-3.5 text-text-muted group-open/cat:rotate-180 transition-transform ml-auto" />
                </summary>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {catItems.map(m => (
                    <MappingCard
                      key={m._idx}
                      m={m}
                      sourceProvider={sourceProvider}
                      onClick={() => { onViewChange?.('table'); setExpandedRow(m._idx); }}
                    />
                  ))}
                </div>
              </details>
            );
          })}

          <p className="text-[10px] text-text-muted text-right">
            Showing {sorted.length} of {mappings.length} services
          </p>
        </>
      )}

      {/* Table View */}
      {activeView === 'table' && (
        <>
          <details open className="group">
            <summary className="flex items-center gap-2 text-xs text-text-muted cursor-pointer hover:text-text-primary mb-2">
              <Filter className="w-3.5 h-3.5" /> Filters
              <ChevronDown className="w-3 h-3 group-open:rotate-180 transition-transform" />
            </summary>
            <div className="mb-2">
              <FilterBar filters={filters} categories={allCategories} onFilterChange={setFilters} />
            </div>
          </details>

          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <div className="max-h-[600px] overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 z-10 bg-secondary border-b border-border">
                    <tr>
                      {[
                        { id: 'source', label: 'Source Service' },
                        { id: 'target', label: 'Target Service' },
                        { id: 'confidence', label: 'Confidence' },
                        { id: 'effort', label: 'Effort' },
                        { id: 'category', label: 'Category' },
                        { id: 'gaps', label: 'Gaps' },
                      ].map(col => (
                        <th
                          key={col.id}
                          onClick={() => handleSort(col.id)}
                          className="px-4 py-3 text-left font-semibold text-text-secondary cursor-pointer hover:text-text-primary select-none"
                        >
                          <span className="inline-flex items-center gap-1.5">
                            {col.label}
                            <SortIcon col={col.id} />
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-4 py-8 text-center text-text-muted">No services match the current filters</td>
                      </tr>
                    )}
                    {sorted.map((m, i) => {
                      const isExpanded = expandedRow === m._idx;
                      return (
                        <React.Fragment key={m._idx}>
                          <tr
                            ref={el => { rowRefs.current[m._idx] = el; }}
                            onClick={() => setExpandedRow(isExpanded ? null : m._idx)}
                            className={`cursor-pointer transition-colors border-b border-border ${
                              i % 2 === 0 ? 'bg-primary' : 'bg-surface/30'
                            } ${isExpanded ? 'bg-cta/5' : 'hover:bg-secondary/50'}`}
                          >
                            <td className="px-4 py-3">
                              <span className={`font-medium ${sourceProvider === 'gcp' ? 'text-[#EA4335]' : 'text-[#FF9900]'}`}>
                                {m._source}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-info font-medium">{m._target}</span>
                            </td>
                            <td className="px-4 py-3">
                              <Badge variant={m._confidence >= 90 ? 'high' : m._confidence >= 70 ? 'medium' : 'low'}>
                                {m._confidence.toFixed(0)}%
                              </Badge>
                            </td>
                            <td className="px-4 py-3">
                              <Badge variant={m._effort === 'low' ? 'high' : m._effort === 'high' ? 'low' : 'medium'}>
                                {m._effort}
                              </Badge>
                            </td>
                            <td className="px-4 py-3 text-text-muted">{m._category}</td>
                            <td className="px-4 py-3">
                              {m._gaps.length > 0 ? (
                                <span className="flex items-center gap-1 text-warning">
                                  <AlertTriangle className="w-3 h-3" />{m._gaps.length}
                                </span>
                              ) : (
                                <CheckCircle2 className="w-3.5 h-3.5 text-cta" />
                              )}
                            </td>
                          </tr>

                          {/* Expanded detail row */}
                          {isExpanded && (
                            <tr className="bg-cta/5">
                              <td colSpan={6} className="px-6 py-4">
                                <div className="space-y-2 text-xs">
                                  <div className="flex gap-6">
                                    <div>
                                      <span className="text-text-muted">Source:</span>{' '}
                                      <span className="text-text-primary font-medium">{m._source}</span>
                                    </div>
                                    <div>
                                      <span className="text-text-muted">Target:</span>{' '}
                                      <span className="text-info font-medium">{m._target}</span>
                                    </div>
                                    {m.notes && (
                                      <div>
                                        <span className="text-text-muted">Notes:</span>{' '}
                                        <span className="text-text-secondary">{m.notes}</span>
                                      </div>
                                    )}
                                  </div>

                                  {/* Confidence explanation */}
                                  {m.confidence_explanation?.length > 0 && (
                                    <div className="pl-3 border-l-2 border-cta/30 space-y-1 mt-2">
                                      <p className="text-text-secondary font-semibold">Confidence breakdown:</p>
                                      {m.confidence_explanation.map((reason, idx) => (
                                        <div key={idx} className="flex items-start gap-2 text-text-muted">
                                          <span className="text-cta/60 mt-0.5">•</span>
                                          <span>{reason}</span>
                                        </div>
                                      ))}
                                    </div>
                                  )}

                                  {/* Confidence Provenance Detail (#431) */}
                                  {m.confidence_provenance && (
                                    <div className="space-y-3 mt-3">
                                      {/* Score Decomposition */}
                                      {m.confidence_provenance.score_decomposition && (
                                        <div className="pl-3 border-l-2 border-info/30 space-y-1">
                                          <p className="text-text-secondary font-semibold text-xs">Score breakdown:</p>
                                          {Object.entries(m.confidence_provenance.score_decomposition.components || {}).map(([key, comp]) => (
                                            <div key={key} className="flex items-center gap-2 text-text-muted text-xs">
                                              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: comp.score >= 80 ? '#22C55E' : comp.score >= 60 ? '#F59E0B' : '#EF4444' }} />
                                              <span className="capitalize">{key.replace(/_/g, ' ')}</span>
                                              <span className="text-text-secondary font-medium">{Math.round(comp.score)}%</span>
                                              <span className="text-text-muted/60">×{comp.weight}</span>
                                            </div>
                                          ))}
                                        </div>
                                      )}

                                      {/* Feature Parity */}
                                      {m.confidence_provenance.feature_parity && (
                                        <div className="pl-3 border-l-2 border-cta/30 space-y-1">
                                          <p className="text-text-secondary font-semibold text-xs">
                                            Feature parity: <span className="text-cta">{m.confidence_provenance.feature_parity.parity_score}</span>
                                          </p>
                                          <div className="flex flex-wrap gap-1">
                                            {(m.confidence_provenance.feature_parity.matched_features || []).map((f, i) => (
                                              <span key={i} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-green-500/10 text-green-400">✓ {f}</span>
                                            ))}
                                            {(m.confidence_provenance.feature_parity.missing_features || []).map((f, i) => (
                                              <span key={i} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-red-500/10 text-red-400">✗ {f}</span>
                                            ))}
                                          </div>
                                        </div>
                                      )}

                                      {/* Migration Guidance */}
                                      {m.confidence_provenance.migration_guidance && (
                                        <div className="pl-3 border-l-2 border-purple-500/30 space-y-1">
                                          <p className="text-text-secondary font-semibold text-xs">
                                            Migration effort: <span className={
                                              m.confidence_provenance.migration_guidance.estimated_effort === 'low' ? 'text-green-400' :
                                              m.confidence_provenance.migration_guidance.estimated_effort === 'medium' ? 'text-yellow-400' : 'text-red-400'
                                            }>{m.confidence_provenance.migration_guidance.estimated_effort}</span>
                                          </p>
                                          {m.confidence_provenance.migration_guidance.migration_notes && (
                                            <p className="text-text-muted text-xs">{m.confidence_provenance.migration_guidance.migration_notes}</p>
                                          )}
                                          {(m.confidence_provenance.migration_guidance.breaking_changes || []).length > 0 && (
                                            <div className="space-y-0.5">
                                              {m.confidence_provenance.migration_guidance.breaking_changes.map((bc, i) => (
                                                <div key={i} className="flex items-start gap-1 text-[10px] text-red-400">
                                                  <span>⚠</span><span>{bc}</span>
                                                </div>
                                              ))}
                                            </div>
                                          )}
                                        </div>
                                      )}

                                      {/* Azure Docs Links */}
                                      {(m.confidence_provenance.azure_docs || []).length > 0 && (
                                        <div className="pl-3 border-l-2 border-blue-500/30">
                                          <div className="flex flex-wrap gap-2">
                                            {m.confidence_provenance.azure_docs.map((doc, i) => (
                                              <a key={i} href={doc.url} target="_blank" rel="noopener noreferrer"
                                                className="text-[10px] text-info hover:underline">📄 {doc.title}</a>
                                            ))}
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  )}

                                  {/* Gaps */}
                                  {m._gaps.length > 0 && (
                                    <div className="pl-3 border-l-2 border-warning/30 space-y-1 mt-2">
                                      <p className="text-warning font-semibold">Feature gaps:</p>
                                      {m._gaps.map((g, idx) => {
                                        const text = typeof g === 'string' ? g : g.factor || '';
                                        const detail = typeof g === 'string' ? null : g.detail;
                                        return (
                                          <div key={idx} className="flex items-start gap-2 text-text-muted">
                                            <AlertTriangle className="w-3 h-3 text-warning shrink-0 mt-0.5" />
                                            <div>
                                              <span className="text-text-primary">{text}</span>
                                              {detail && <span className="text-text-muted"> — {detail}</span>}
                                            </div>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </Card>

          <p className="text-[10px] text-text-muted text-right">
            Showing {sorted.length} of {mappings.length} services
          </p>
        </>
      )}
    </div>
  );
}
