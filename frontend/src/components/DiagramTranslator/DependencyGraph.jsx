import React, { useMemo, useState, useCallback, useRef } from 'react';
import {
  ReactFlow, ReactFlowProvider, Controls, Background, MiniMap,
  useNodesState, useEdgesState, useReactFlow, Handle, Position,
} from '@xyflow/react';
import dagre from 'dagre';
import '@xyflow/react/dist/style.css';
import {
  X, Download, Network, Server, Database, Shield, HardDrive,
  Globe, Zap, Info, ChevronRight, AlertTriangle,
} from 'lucide-react';

/* ── Constants ─────────────────────────────────────────── */
const NODE_W = 220;
const NODE_H = 72;

const CATEGORY_BORDER = {
  Compute: '#3B82F6',
  Networking: '#A855F7',
  Database: '#22C55E',
  Security: '#EF4444',
  Storage: '#14B8A6',
  'AI/ML': '#EC4899',
};

const EDGE_COLORS = {
  traffic:  { stroke: '#3B82F6', strokeWidth: 2, strokeDasharray: undefined },
  database: { stroke: '#22C55E', strokeWidth: 2, strokeDasharray: undefined },
  auth:     { stroke: '#A855F7', strokeWidth: 1.5, strokeDasharray: '6,4' },
  control:  { stroke: '#94A3B8', strokeWidth: 1.5, strokeDasharray: '6,4' },
  security: { stroke: '#F97316', strokeWidth: 2, strokeDasharray: '2,3' },
  storage:  { stroke: '#14B8A6', strokeWidth: 1.5, strokeDasharray: undefined },
};
const DEFAULT_EDGE_STYLE = { stroke: '#3B82F6', strokeWidth: 2 };

const CATEGORY_ICON = {
  Compute: Server,
  Networking: Globe,
  Database: Database,
  Security: Shield,
  Storage: HardDrive,
  'AI/ML': Zap,
};

/* ── Custom Node ───────────────────────────────────────── */
function ServiceNode({ data, selected }) {
  const { label, azureService, confidence, category, onClick } = data;
  const pct = Math.round((confidence ?? 0) * 100);
  const borderColor = CATEGORY_BORDER[category] || '#64748B';
  const confColor = pct >= 85 ? '#22C55E' : pct >= 60 ? '#F59E0B' : '#EF4444';
  const confBg = pct >= 85 ? 'bg-emerald-500/15' : pct >= 60 ? 'bg-amber-500/15' : 'bg-red-500/15';
  const confText = pct >= 85 ? 'text-emerald-500' : pct >= 60 ? 'text-amber-500' : 'text-red-500';
  const Icon = CATEGORY_ICON[category] || Server;

  return (
    <div
      className={`bg-white rounded-lg shadow-md hover:shadow-lg transition-all duration-150 cursor-pointer ${
        selected ? 'ring-2 ring-blue-400' : ''
      }`}
      style={{ width: NODE_W, borderLeft: `3px solid ${borderColor}` }}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick?.()}
      aria-label={`Service ${label}`}
    >
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-slate-400 !border-white" />
      <div className="px-3 py-2.5">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-text-muted shrink-0" />
          <span className="text-xs font-semibold text-text-primary truncate flex-1">{label}</span>
          <span
            className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${confBg} ${confText}`}
            title={`${pct}% confidence`}
          >
            {pct}%
          </span>
        </div>
        {azureService && (
          <p className="text-[10px] text-text-muted mt-1 truncate pl-6" title={azureService}>
            → {azureService}
          </p>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-slate-400 !border-white" />
    </div>
  );
}

/* ── Zone Group Node ───────────────────────────────────── */
function ZoneGroupNode({ data }) {
  return (
    <div className="w-full h-full relative" style={{ zIndex: -1 }}>
      <div className="absolute top-2 left-3 bg-white/80 backdrop-blur-sm px-2 py-0.5 rounded text-[9px] font-bold text-blue-400 uppercase tracking-wider border border-blue-400/30">
        {data.label}
      </div>
    </div>
  );
}

const nodeTypes = { serviceNode: ServiceNode, zoneGroup: ZoneGroupNode };

/* ── Dagre Layout ──────────────────────────────────────── */
function layoutGraph(nodes, edges) {
  const g = new dagre.graphlib.Graph({ compound: true });
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', ranksep: 90, nodesep: 50 });

  nodes.forEach((n) => {
    if (n.type === 'zoneGroup') {
      g.setNode(n.id, { label: n.data.label, width: NODE_W + 80, height: NODE_H + 50 });
    } else {
      g.setNode(n.id, { width: NODE_W, height: NODE_H });
    }
    if (n.parentId) g.setParent(n.id, n.parentId);
  });

  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  nodes.forEach((n) => {
    const pos = g.node(n.id);
    if (!pos || !Number.isFinite(pos.x) || !Number.isFinite(pos.y)) {
      n.position = { x: 0, y: 0 };
      return;
    }
    n.targetPosition = 'top';
    n.sourcePosition = 'bottom';
    const w = Number.isFinite(pos.width) ? pos.width : NODE_W;
    const h = Number.isFinite(pos.height) ? pos.height : NODE_H;
    let x = pos.x - w / 2;
    let y = pos.y - h / 2;

    if (n.type === 'zoneGroup') {
      n.style = { ...n.style, width: w + 40, height: h + 50 };
      x -= 20;
      y -= 35;
    }

    if (n.parentId) {
      const pp = g.node(n.parentId);
      if (pp && Number.isFinite(pp.x) && Number.isFinite(pp.y)) {
        const ppw = Number.isFinite(pp.width) ? pp.width : 0;
        const pph = Number.isFinite(pp.height) ? pp.height : 0;
        x -= pp.x - ppw / 2 - 20;
        y -= pp.y - pph / 2 - 35;
      }
    }
    n.position = { x, y };
  });
  return { nodes, edges };
}

/* ── Detail Panel ──────────────────────────────────────── */
function DetailPanel({ mapping, onClose }) {
  if (!mapping) return null;

  const src = typeof mapping.source_service === 'object' ? mapping.source_service.name : mapping.source_service;
  const pct = Math.round((mapping.confidence ?? 0) * 100);
  const confColor = pct >= 85 ? 'text-emerald-500' : pct >= 60 ? 'text-amber-500' : 'text-red-500';
  const gaps = mapping.feature_gaps || [];
  const limitations = mapping.limitations || [];

  return (
    <div className="absolute top-4 right-4 z-20 w-72 bg-white border border-border rounded-lg shadow-xl animate-in fade-in slide-in-from-right-2">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h4 className="text-sm font-bold text-text-primary truncate">{src}</h4>
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-surface text-text-muted hover:text-text-primary transition-colors"
          aria-label="Close details"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="p-4 space-y-3 max-h-80 overflow-y-auto">
        {/* Azure Mapping */}
        <div>
          <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-1">Azure Mapping</p>
          <p className="text-xs text-text-primary font-medium">{mapping.azure_service || 'Not mapped'}</p>
        </div>

        {/* Confidence */}
        <div>
          <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-1">Confidence</p>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-surface rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${pct}%`, backgroundColor: pct >= 85 ? '#22C55E' : pct >= 60 ? '#F59E0B' : '#EF4444' }}
              />
            </div>
            <span className={`text-xs font-bold ${confColor}`}>{pct}%</span>
          </div>
        </div>

        {/* Category & Effort */}
        <div className="flex items-center gap-3">
          {mapping.category && (
            <div>
              <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-1">Category</p>
              <span className="text-xs text-text-primary">{mapping.category}</span>
            </div>
          )}
          {mapping.migration_effort && (
            <div>
              <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-1">Effort</p>
              <span className="text-xs text-text-primary capitalize">{mapping.migration_effort}</span>
            </div>
          )}
        </div>

        {/* Feature Gaps */}
        {gaps.length > 0 && (
          <div>
            <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-1">
              Feature Gaps ({gaps.length})
            </p>
            <div className="space-y-1">
              {gaps.slice(0, 5).map((g, i) => (
                <div key={i} className="flex items-start gap-1.5 text-[11px] text-text-secondary">
                  <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0 mt-0.5" />
                  <span>{typeof g === 'string' ? g : g.feature || g.gap || JSON.stringify(g)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Limitations */}
        {limitations.length > 0 && (
          <div>
            <p className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-1">
              Limitations ({limitations.length})
            </p>
            <div className="space-y-1">
              {limitations.slice(0, 3).map((l, i) => {
                const factor = typeof l === 'string' ? l : l.factor || '';
                return (
                  <div key={i} className="flex items-start gap-1.5 text-[11px] text-text-secondary">
                    <Info className="w-3 h-3 text-red-400 shrink-0 mt-0.5" />
                    <span>{factor}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Legend ─────────────────────────────────────────────── */
function DependencyLegend() {
  const [open, setOpen] = useState(true);
  const edgeItems = [
    ['Traffic', '#3B82F6', 'none'],
    ['Database', '#22C55E', 'none'],
    ['Auth', '#A855F7', '6,4'],
    ['Control', '#94A3B8', '6,4'],
    ['Security', '#F97316', '2,3'],
    ['Storage', '#14B8A6', 'none'],
  ];
  const catItems = [
    ['Compute', '#3B82F6'],
    ['Network', '#A855F7'],
    ['Database', '#22C55E'],
    ['Security', '#EF4444'],
    ['Storage', '#14B8A6'],
  ];

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="absolute bottom-4 left-4 z-10 bg-white border border-border rounded-lg px-2.5 py-1.5 text-[10px] text-text-secondary hover:border-slate-500 transition-colors"
      >
        Legend &#x25B8;
      </button>
    );
  }

  return (
    <div className="absolute bottom-4 left-4 z-10 bg-white/95 backdrop-blur-sm border border-border rounded-lg p-3 w-44 shadow-xl">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-bold text-text-secondary uppercase tracking-wider">Legend</span>
        <button onClick={() => setOpen(false)} className="text-text-muted hover:text-text-secondary text-xs">&#x2715;</button>
      </div>

      {/* Edge types */}
      <p className="text-[9px] text-text-muted font-semibold uppercase mb-1">Connections</p>
      <div className="space-y-1 mb-2.5">
        {edgeItems.map(([label, color, dash]) => (
          <div key={label} className="flex items-center gap-2">
            <svg width="16" height="6">
              <line x1="0" y1="3" x2="16" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dash} />
            </svg>
            <span className="text-[9px] text-text-muted">{label}</span>
          </div>
        ))}
      </div>

      {/* Category borders */}
      <p className="text-[9px] text-text-muted font-semibold uppercase mb-1 pt-2 border-t border-border/50">Categories</p>
      <div className="space-y-1 mb-2.5">
        {catItems.map(([label, color]) => (
          <div key={label} className="flex items-center gap-2">
            <div className="w-1.5 h-3 rounded-sm" style={{ backgroundColor: color }} />
            <span className="text-[9px] text-text-muted">{label}</span>
          </div>
        ))}
      </div>

      {/* Confidence */}
      <p className="text-[9px] text-text-muted font-semibold uppercase mb-1 pt-2 border-t border-border/50">Confidence</p>
      <div className="space-y-1">
        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-emerald-500" /><span className="text-[9px] text-text-muted">{'\u2265'}85%</span></div>
        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-amber-500" /><span className="text-[9px] text-text-muted">60–84%</span></div>
        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-red-500" /><span className="text-[9px] text-text-muted">&lt;60%</span></div>
      </div>
    </div>
  );
}

/* ── Inner Canvas (must be inside ReactFlowProvider) ───── */
function GraphCanvas({ initialNodes, initialEdges, mappingsMap }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [selected, setSelected] = useState(null);
  const { toObject } = useReactFlow();

  React.useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
    setSelected(null);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  const handleNodeClick = useCallback((_event, node) => {
    if (node.type === 'zoneGroup') return;
    const mapping = mappingsMap[node.id];
    setSelected(mapping || null);
  }, [mappingsMap]);

  const handleExportSvg = useCallback(() => {
    const flowEl = document.querySelector('.dep-graph-flow .react-flow__viewport');
    if (!flowEl) return;

    const svgNs = 'http://www.w3.org/2000/svg';
    const svgEl = document.createElementNS(svgNs, 'svg');
    const clone = flowEl.cloneNode(true);

    // compute bounding box from the flow viewport
    const rect = flowEl.getBoundingClientRect();
    svgEl.setAttribute('xmlns', svgNs);
    svgEl.setAttribute('width', String(rect.width));
    svgEl.setAttribute('height', String(rect.height));
    svgEl.setAttribute('viewBox', `0 0 ${rect.width} ${rect.height}`);

    const fo = document.createElementNS(svgNs, 'foreignObject');
    fo.setAttribute('width', '100%');
    fo.setAttribute('height', '100%');
    fo.appendChild(clone);
    svgEl.appendChild(fo);

    const blob = new Blob([new XMLSerializer().serializeToString(svgEl)], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'dependency-graph.svg';
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  if (!nodes.length) {
    return (
      <div className="w-full h-64 flex flex-col items-center justify-center text-text-muted bg-white rounded-lg border border-border gap-2">
        <Network className="w-8 h-8 text-text-muted/50" />
        <p className="text-sm">No service connections detected</p>
        <p className="text-xs text-text-muted/70">The analysis didn't find inter-service dependencies to visualize.</p>
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '550px' }} className="relative rounded-lg border border-border bg-white dep-graph-flow">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        attributionPosition="bottom-right"
      >
        <Background color="#e2e8f0" gap={18} size={1} variant="dots" />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={2}
          nodeColor={(n) => {
            if (n.type === 'zoneGroup') return 'transparent';
            const cat = n.data?.category;
            return CATEGORY_BORDER[cat] || '#64748B';
          }}
          maskColor="rgba(255,255,255,0.75)"
          style={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8 }}
          pannable
          zoomable
        />
      </ReactFlow>

      {/* Export button */}
      <button
        onClick={handleExportSvg}
        className="absolute top-3 right-3 z-10 flex items-center gap-1.5 bg-white border border-border rounded-lg px-2.5 py-1.5 text-[11px] text-text-secondary hover:border-slate-500 hover:text-text-primary transition-colors shadow-sm"
        title="Export as SVG"
      >
        <Download className="w-3.5 h-3.5" />
        Export SVG
      </button>

      <DependencyLegend />
      <DetailPanel mapping={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

/* ── Main Component ────────────────────────────────────── */
export default function DependencyGraph({ analysis }) {
  const { initialNodes, initialEdges, mappingsMap } = useMemo(() => {
    const mappings = analysis?.mappings || [];
    const connections = analysis?.service_connections || [];
    const zones = analysis?.zones || [];
    const nodes = [];
    const edges = [];
    const mMap = {};

    // Build quick lookup: source name → mapping
    mappings.forEach((m) => {
      const src = typeof m.source_service === 'object' ? m.source_service.name : m.source_service;
      mMap[src] = m;
    });

    // Create zone group nodes
    zones.forEach((z) => {
      nodes.push({
        id: `zone-${z.name}`,
        type: 'zoneGroup',
        data: { label: z.name },
        position: { x: 0, y: 0 },
        style: {
          backgroundColor: 'rgba(59,130,246,0.04)',
          border: '1px dashed rgba(59,130,246,0.25)',
          borderRadius: '8px',
          zIndex: -1,
        },
      });
    });

    // Create service nodes
    mappings.forEach((m) => {
      const src = typeof m.source_service === 'object' ? m.source_service.name : m.source_service;
      const parentZone = zones.find((z) =>
        z.services?.some((s) => (typeof s === 'string' ? s : s?.name) === src),
      );

      nodes.push({
        id: src,
        type: 'serviceNode',
        parentId: parentZone ? `zone-${parentZone.name}` : undefined,
        draggable: true,
        data: {
          label: src,
          azureService: m.azure_service,
          confidence: m.confidence ?? 0,
          category: m.category || '',
        },
        position: { x: 0, y: 0 },
      });
    });

    // Create edges from service_connections
    connections.forEach((c, i) => {
      const fromExists = nodes.some((n) => n.id === c.from);
      const toExists = nodes.some((n) => n.id === c.to);
      if (!fromExists || !toExists) return;

      const connType = (c.type || '').toLowerCase();
      const style = EDGE_COLORS[connType] || DEFAULT_EDGE_STYLE;

      edges.push({
        id: `dep-${i}-${c.from}-${c.to}`,
        source: c.from,
        target: c.to,
        animated: !style.strokeDasharray,
        label: c.protocol || '',
        style,
        labelStyle: { fill: '#64748B', fontWeight: 600, fontSize: 9 },
        labelBgStyle: { fill: '#ffffff', fillOpacity: 0.9 },
        labelBgPadding: [4, 2],
      });
    });

    const laid = layoutGraph([...nodes], [...edges]);
    return { initialNodes: laid.nodes, initialEdges: laid.edges, mappingsMap: mMap };
  }, [analysis]);

  return (
    <ReactFlowProvider>
      <GraphCanvas
        initialNodes={initialNodes}
        initialEdges={initialEdges}
        mappingsMap={mappingsMap}
      />
    </ReactFlowProvider>
  );
}
