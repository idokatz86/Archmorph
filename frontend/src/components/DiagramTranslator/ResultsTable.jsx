import React, { useState, useMemo, useCallback, useRef } from 'react';
import {
  ArrowUpDown, ArrowUp, ArrowDown, Filter, ChevronDown, ChevronUp,
  AlertTriangle, CheckCircle2, ArrowRight, X,
} from 'lucide-react';
import { Badge, Card } from '../ui';

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
  const needsReview = med + low + noMatch;

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
        <div className="flex items-center gap-1.5">
          <span className="font-bold text-text-primary text-lg">{total}</span>
          <span className="text-text-muted">services total</span>
        </div>
        <div className="h-6 w-px bg-border hidden sm:block" />
        <div className="flex items-center gap-3">
          <span className="text-cta font-semibold">{high} high</span>
          <span className="text-warning font-semibold">{med} med</span>
          <span className="text-danger font-semibold">{low} low</span>
          {noMatch > 0 && <span className="text-text-muted font-semibold">{noMatch} none</span>}
        </div>
        <div className="h-6 w-px bg-border hidden sm:block" />
        <div className="flex items-center gap-2 text-text-muted">
          Effort: <span className="text-cta">{effortLow} low</span> / <span className="text-warning">{effortMed} med</span> / <span className="text-danger">{effortHigh} high</span>
        </div>
        <div className="h-6 w-px bg-border hidden sm:block" />
        <div className="flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 text-warning" />
          <span className="text-text-muted">{gapCount} with gaps</span>
        </div>
      </div>
      <p className="text-xs text-text-secondary mt-2">
        {automatable}% high-confidence.{needsReview > 0 ? ` ${needsReview} service${needsReview > 1 ? 's' : ''} need${needsReview === 1 ? 's' : ''} review.` : ' All services map cleanly.'}
      </p>
    </Card>
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
      <SummaryBar mappings={mappings} />

      {/* View Toggle */}
      <div className="flex items-center gap-1 bg-secondary rounded-xl p-1 w-fit">
        {[
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

      {/* Table View */}
      {activeView === 'table' && (
        <>
          <FilterBar filters={filters} categories={allCategories} onFilterChange={setFilters} />

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
