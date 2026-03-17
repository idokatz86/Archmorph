import React, { useMemo } from 'react';
import {
  ReactFlow, Controls, Background, MiniMap,
  applyNodeChanges, applyEdgeChanges, Handle, Position,
} from '@xyflow/react';
import dagre from 'dagre';
import '@xyflow/react/dist/style.css';
import { FaAws } from 'react-icons/fa';
import { VscAzure } from 'react-icons/vsc';
import { SiGooglecloud } from 'react-icons/si';
import { ArrowRight, Database, Server, Zap, HardDrive, AlertTriangle } from 'lucide-react';

const NODE_WIDTH = 270;
const NODE_HEIGHT = 100;

const getCloudIcon = (name, fallback) => {
  if (!name) return fallback;
  const s = name.toLowerCase();
  if (s.includes('lambda') || s.includes('functions')) return <Zap className="w-4 h-4 text-text-muted" />;
  if (s.includes('ec2') || s.includes('compute')) return <Server className="w-4 h-4 text-text-muted" />;
  if (s.includes('s3') || s.includes('blob')) return <HardDrive className="w-4 h-4 text-text-muted" />;
  if (s.includes('rds') || s.includes('cosmos') || s.includes('aurora')) return <Database className="w-4 h-4 text-text-muted" />;
  return fallback;
};

/* Edge type visual styles — per Cloud Architect specification */
const EDGE_STYLES = {
  traffic: { stroke: '#3B82F6', strokeWidth: 2 },
  database: { stroke: '#22C55E', strokeWidth: 2 },
  auth: { stroke: '#A855F7', strokeWidth: 1.5, strokeDasharray: '6,4' },
  control: { stroke: '#94A3B8', strokeWidth: 1.5, strokeDasharray: '6,4' },
  inspection: { stroke: '#F97316', strokeWidth: 2, strokeDasharray: '3,3' },
  security: { stroke: '#F97316', strokeWidth: 2, strokeDasharray: '3,3' },
  storage: { stroke: '#14B8A6', strokeWidth: 1.5 },
  backup: { stroke: '#14B8A6', strokeWidth: 1.5 },
  metrics: { stroke: '#94A3B8', strokeWidth: 1.5, strokeDasharray: '6,4' },
};
const DEFAULT_EDGE = { stroke: '#3B82F6', strokeWidth: 2 };

/* ── MappingNode with confidence ring, effort badge, category, feature gaps ── */
function MappingNode({ data }) {
  const { source, target, provider, confidence, effort, category, featureGaps } = data;
  const pLower = (provider || 'aws').toLowerCase();
  const PIcon = pLower === 'gcp' ? <SiGooglecloud className="w-4 h-4 text-[#EA4335]" /> : <FaAws className="w-4 h-4 text-[#FF9900]" />;

  const pct = Math.round((confidence ?? 0) * 100);
  const cColor = pct >= 85 ? 'text-emerald-400' : pct >= 60 ? 'text-amber-400' : 'text-red-400';
  const cRing = pct >= 85 ? 'stroke-emerald-400' : pct >= 60 ? 'stroke-amber-400' : 'stroke-red-400';

  const effortMap = {
    low: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    medium: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    high: 'bg-red-500/20 text-red-400 border-red-500/30',
  };
  const eCls = effortMap[effort] || effortMap.medium;

  const catMap = {
    Compute: 'bg-blue-500/15 text-blue-400',
    Networking: 'bg-purple-500/15 text-purple-400',
    Database: 'bg-green-500/15 text-green-400',
    Security: 'bg-red-500/15 text-red-400',
    Storage: 'bg-teal-500/15 text-teal-400',
    'AI/ML': 'bg-pink-500/15 text-pink-400',
  };
  const catCls = catMap[category] || 'bg-slate-500/15 text-text-muted';
  const gaps = featureGaps?.length || 0;
  const circ = 2 * Math.PI * 14;
  const off = circ - (circ * pct / 100);

  return (
    <div className="bg-white border border-border rounded-lg shadow-lg min-w-[260px] hover:border-[#22C55E]/50 hover:shadow-xl transition-all duration-200">
      <Handle type="target" position={Position.Top} className="w-2.5 h-2.5 !bg-slate-500" />
      {/* Top bar: category + effort + gap count */}
      <div className="flex items-center justify-between px-3 pt-2 pb-1.5 border-b border-border/50">
        <span className={`text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${catCls}`}>{category || 'Service'}</span>
        <div className="flex items-center gap-1.5">
          {effort && <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border ${eCls}`}>{effort}</span>}
          {gaps > 0 && (
            <span className="flex items-center gap-0.5 text-[9px] text-amber-400" title={`${gaps} feature gap(s)`}>
              <AlertTriangle className="w-3 h-3" />{gaps}
            </span>
          )}
        </div>
      </div>
      {/* Main: confidence ring + source -> target */}
      <div className="flex items-center gap-3 px-3 py-2">
        <div className="relative flex-shrink-0 w-9 h-9" title={`${pct}% confidence`}>
          <svg className="w-9 h-9 -rotate-90" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="14" fill="none" stroke="currentColor" className="text-slate-700" strokeWidth="3" />
            <circle cx="18" cy="18" r="14" fill="none" className={cRing} strokeWidth="3" strokeLinecap="round"
              strokeDasharray={circ} strokeDashoffset={off} />
          </svg>
          <span className={`absolute inset-0 flex items-center justify-center text-[9px] font-bold ${cColor}`}>{pct}</span>
        </div>
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <div className="flex flex-col items-center gap-0.5 min-w-0 flex-1">
            {getCloudIcon(source, PIcon)}
            <span className="text-[10px] font-medium text-text-secondary text-center leading-tight truncate w-full">{source}</span>
          </div>
          <ArrowRight className="w-3.5 h-3.5 text-text-muted flex-shrink-0" />
          <div className="flex flex-col items-center gap-0.5 min-w-0 flex-1">
            {getCloudIcon(target, <VscAzure className="w-4 h-4 text-[#0089D6]" />)}
            <span className="text-[10px] font-bold text-text-primary text-center leading-tight truncate w-full">{target || 'Pending'}</span>
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="w-2.5 h-2.5 !bg-slate-500" />
    </div>
  );
}

/* ── ManualMappingNode — red dashed node for unmapped services ── */
function ManualMappingNode({ data }) {
  const { source, provider } = data;
  const PIcon = (provider || 'aws').toLowerCase() === 'gcp'
    ? <SiGooglecloud className="w-4 h-4 text-[#EA4335]" />
    : <FaAws className="w-4 h-4 text-[#FF9900]" />;

  return (
    <div className="bg-red-950/40 border-2 border-dashed border-red-500/60 rounded-lg shadow-lg min-w-[220px] hover:border-red-400 transition-all">
      <Handle type="target" position={Position.Top} className="w-2.5 h-2.5 !bg-red-500" />
      <div className="flex items-center gap-3 px-3 py-3">
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center">
          <AlertTriangle className="w-4 h-4 text-red-400" />
        </div>
        <div className="flex flex-col min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {getCloudIcon(source, PIcon)}
            <span className="text-[11px] font-semibold text-red-300 truncate">{source}</span>
          </div>
          <span className="text-[9px] text-red-400/80 mt-0.5">Manual mapping required</span>
        </div>
        <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30">Review</span>
      </div>
      <Handle type="source" position={Position.Bottom} className="w-2.5 h-2.5 !bg-red-500" />
    </div>
  );
}

/* ── GroupNode ── */
function GroupNode({ data }) {
  return (
    <div className="w-full h-full relative" style={{ zIndex: -1 }}>
      <div className="absolute top-2 left-3 bg-white/80 backdrop-blur-sm px-2.5 py-1 rounded-md text-[10px] font-bold text-blue-300 uppercase tracking-wider border border-blue-500/30 shadow-sm">
        {data.label}
      </div>
    </div>
  );
}

/* ── MapLegend overlay ── */
function MapLegend() {
  const [open, setOpen] = React.useState(true);
  const items = [
    ['Traffic', '#3B82F6', 'none'], ['Database', '#22C55E', 'none'],
    ['Auth', '#A855F7', '4,3'], ['Control', '#94A3B8', '4,3'],
    ['Security', '#F97316', '2,2'], ['Storage', '#14B8A6', 'none'],
  ];

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="absolute bottom-4 left-4 z-10 bg-white border border-border rounded-lg px-2.5 py-1.5 text-[10px] text-text-secondary hover:border-slate-500 transition-colors">
        Legend &#x25B8;
      </button>
    );
  }

  return (
    <div className="absolute bottom-4 left-4 z-10 bg-white/95 backdrop-blur-sm border border-border rounded-lg p-3 w-48 shadow-xl">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-bold text-text-secondary uppercase tracking-wider">Legend</span>
        <button onClick={() => setOpen(false)} className="text-text-muted hover:text-text-secondary text-xs">&#x2715;</button>
      </div>
      <div className="space-y-1.5 mb-2.5">
        <div className="flex items-center gap-2"><div className="w-4 h-3 rounded-sm border border-border bg-white" /><span className="text-[9px] text-text-muted">Mapped service</span></div>
        <div className="flex items-center gap-2"><div className="w-4 h-3 rounded-sm border-2 border-dashed border-red-500/60 bg-red-950/40" /><span className="text-[9px] text-text-muted">Manual mapping needed</span></div>
      </div>
      <div className="border-t border-border/50 pt-2 space-y-1">
        {items.map(([l, c, d]) => (
          <div key={l} className="flex items-center gap-2">
            <svg width="18" height="6"><line x1="0" y1="3" x2="18" y2="3" stroke={c} strokeWidth="2" strokeDasharray={d} /></svg>
            <span className="text-[9px] text-text-muted">{l}</span>
          </div>
        ))}
      </div>
      <div className="border-t border-border/50 pt-2 mt-2 space-y-1">
        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-emerald-400" /><span className="text-[9px] text-text-muted">{'\u2265'}85% conf.</span></div>
        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-amber-400" /><span className="text-[9px] text-text-muted">60-84%</span></div>
        <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-red-400" /><span className="text-[9px] text-text-muted">&lt;60%</span></div>
      </div>
    </div>
  );
}

const nodeTypes = { mappingNode: MappingNode, manualNode: ManualMappingNode, groupNode: GroupNode };

/* ── Dagre layout engine ── */
const getLayoutedElements = (nodes, edges) => {
  const g = new dagre.graphlib.Graph({ compound: true });
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', ranksep: 100, nodesep: 80 });

  nodes.forEach((n) => {
    if (n.type === 'groupNode') g.setNode(n.id, { label: n.data.label, clusterLabelPos: 'top' });
    else g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    if (n.parentId) g.setParent(n.id, n.parentId);
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  nodes.forEach((n) => {
    const p = g.node(n.id);
    n.targetPosition = 'top';
    n.sourcePosition = 'bottom';
    let x = p.x - p.width / 2;
    let y = p.y - p.height / 2;
    if (n.type === 'groupNode') {
      n.style = { ...n.style, width: (p.width || NODE_WIDTH) + 40, height: (p.height || NODE_HEIGHT) + 60 };
      x -= 20;
      y -= 40;
    }
    if (n.parentId) {
      const pp = g.node(n.parentId);
      x -= pp.x - (pp.width || 0) / 2 - 20;
      y -= pp.y - (pp.height || 0) / 2 - 40;
    }
    n.position = { x, y };
  });
  return { nodes, edges };
};

export default function ArchitectureFlow({ analysis }) {
  const { initialNodes, initialEdges } = useMemo(() => {
    const mappings = analysis?.mappings || [];
    const connections = analysis?.service_connections || [];
    const zones = analysis?.zones || [];
    const nodes = [];
    const edges = [];

    // Zone groups
    zones.forEach((z) => {
      nodes.push({
        id: `zone-${z.name}`, type: 'groupNode', data: { label: z.name },
        position: { x: 0, y: 0 },
        style: { backgroundColor: 'rgba(59,130,246,0.05)', border: '1px dashed rgba(59,130,246,0.3)', borderRadius: '8px', zIndex: -1 },
      });
    });

    // Service nodes — including manual-mapping-needed (#P0)
    mappings.forEach((m) => {
      const src = typeof m.source_service === 'object' ? m.source_service.name : m.source_service;
      const manual = !m.azure_service || m.azure_service === '[Manual mapping needed]';
      const pz = zones.find((z) => z.services?.includes(src));

      nodes.push({
        id: src,
        type: manual ? 'manualNode' : 'mappingNode',
        parentId: pz ? `zone-${pz.name}` : undefined,
        draggable: true,
        data: {
          source: src,
          target: manual ? null : m.azure_service,
          provider: analysis?.source_provider || m.source_provider || 'aws',
          confidence: m.confidence ?? 0,
          effort: m.migration_effort || 'medium',
          category: m.category || '',
          featureGaps: m.feature_gaps || [],
        },
        position: { x: 0, y: 0 },
      });
    });

    // Typed edges (#P1)
    connections.forEach((c, i) => {
      if (nodes.find((n) => n.id === c.from) && nodes.find((n) => n.id === c.to)) {
        const s = EDGE_STYLES[(c.type || '').toLowerCase()] || DEFAULT_EDGE;
        edges.push({
          id: `e${i}-${c.from}-${c.to}`,
          source: c.from, target: c.to,
          animated: !s.strokeDasharray,
          label: c.protocol || '',
          style: s,
          labelStyle: { fill: '#94A3B8', fontWeight: 600, fontSize: 10 },
          labelBgStyle: { fill: '#ffffff', fillOpacity: 0.9 },
        });
      }
    });

    const layouted = getLayoutedElements(nodes, edges);
    return { initialNodes: layouted.nodes, initialEdges: layouted.edges };
  }, [analysis]);

  const [nodes, setNodes] = React.useState(initialNodes);
  const [edges, setEdges] = React.useState(initialEdges);

  React.useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges]);

  const onNodesChange = React.useCallback((changes) => setNodes((nds) => applyNodeChanges(changes, nds)), []);
  const onEdgesChange = React.useCallback((changes) => setEdges((eds) => applyEdgeChanges(changes, eds)), []);

  if (!nodes.length) {
    return (
      <div className="w-full h-64 flex items-center justify-center text-text-muted bg-white rounded-lg border border-border">
        No architecture diagram data available.
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '600px' }} className="relative rounded-lg border border-border overflow-hidden bg-white">
      <ReactFlow
        nodes={nodes} edges={edges}
        onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.15 }}
        nodesDraggable
        panOnDrag
        zoomOnScroll
        zoomOnPinch
        panOnScroll={false}
        selectionOnDrag={false}
        attributionPosition="bottom-right" minZoom={0.3} maxZoom={1.5}
      >
        <Background color="#e2e8f0" gap={20} size={1} />
        <Controls />
        <MiniMap
          nodeStrokeWidth={3}
          nodeColor={(n) => n.type === 'manualNode' ? '#EF4444' : n.type === 'groupNode' ? 'transparent' : '#22C55E'}
          maskColor="rgba(255,255,255,0.7)"
          style={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8 }}
          pannable zoomable
        />
      </ReactFlow>
      <MapLegend />
    </div>
  );
}
