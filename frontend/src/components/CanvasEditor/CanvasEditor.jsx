import React, { useState, useCallback, useRef, useMemo } from 'react';
import {
  ReactFlow, ReactFlowProvider, Controls, Background, MiniMap,
  useNodesState, useEdgesState, useReactFlow, Handle, Position,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Search, Trash2, Download, Undo2, Redo2, Zap, GripVertical,
  Server, Database, Globe, Shield, HardDrive, Brain,
  Plus, X, Play, SquareDashed, ChevronDown, ChevronRight,
} from 'lucide-react';
import { Button, Badge } from '../ui';
import { API_BASE } from '../../constants';
import api from '../../services/apiClient';
import SERVICES, { CATEGORIES, PROVIDERS } from './servicesPalette';

/* ── Category styling (matches DependencyGraph) ─────── */
const CATEGORY_BORDER = {
  Compute: '#3B82F6',
  Network: '#A855F7',
  Database: '#22C55E',
  Security: '#EF4444',
  Storage: '#14B8A6',
  'AI/ML': '#EC4899',
};

const CATEGORY_ICON = {
  Compute: Server,
  Network: Globe,
  Database: Database,
  Security: Shield,
  Storage: HardDrive,
  'AI/ML': Brain,
};

const PROVIDER_BADGE = {
  AWS: { bg: 'bg-[#FF9900]/15', text: 'text-[#FF9900]', border: 'border-[#FF9900]/30' },
  Azure: { bg: 'bg-[#0078D4]/15', text: 'text-[#0078D4]', border: 'border-[#0078D4]/30' },
  GCP: { bg: 'bg-[#4285F4]/15', text: 'text-[#4285F4]', border: 'border-[#4285F4]/30' },
};

/* ── Custom Service Node ───────────────────────────────── */
function CanvasServiceNode({ id, data, selected }) {
  const { name, provider, category, icon_letter, color, notes, onDelete, onNotesChange } = data;
  const borderColor = CATEGORY_BORDER[category] || '#64748B';
  const badge = PROVIDER_BADGE[provider] || PROVIDER_BADGE.AWS;
  const [editing, setEditing] = useState(false);

  return (
    <div
      className={`bg-primary rounded-lg shadow-md hover:shadow-lg transition-all duration-150 group ${
        selected ? 'ring-2 ring-cta' : ''
      }`}
      style={{ width: 200, borderLeft: `3px solid ${borderColor}` }}
    >
      <Handle type="target" position={Position.Top} className="!w-2.5 !h-2.5 !bg-text-muted !border-surface" />
      <Handle type="target" position={Position.Left} className="!w-2.5 !h-2.5 !bg-text-muted !border-surface" />

      <div className="px-3 py-2.5 relative">
        {/* Delete button */}
        <button
          onClick={(e) => { e.stopPropagation(); onDelete?.(id); }}
          className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-danger text-surface flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
          aria-label="Delete node"
        >
          <X className="w-3 h-3" />
        </button>

        <div className="flex items-center gap-2">
          {/* Icon circle */}
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
            style={{ backgroundColor: color || borderColor }}
          >
            {icon_letter}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-text-primary truncate">{name}</p>
            <span className={`inline-flex text-[9px] font-medium px-1.5 py-0.5 rounded border mt-0.5 ${badge.bg} ${badge.text} ${badge.border}`}>
              {provider}
            </span>
          </div>
        </div>

        {/* Editable notes */}
        {editing ? (
          <input
            className="mt-1.5 w-full text-[10px] bg-secondary border border-border rounded px-1.5 py-1 text-text-secondary focus:outline-none focus:border-cta"
            defaultValue={notes || ''}
            placeholder="Tier / config notes…"
            autoFocus
            onBlur={(e) => { setEditing(false); onNotesChange?.(id, e.target.value); }}
            onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); }}
          />
        ) : (
          <p
            className="mt-1.5 text-[10px] text-text-muted truncate cursor-text hover:text-text-secondary"
            onClick={() => setEditing(true)}
            title="Click to edit notes"
          >
            {notes || 'Click to add notes…'}
          </p>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!w-2.5 !h-2.5 !bg-text-muted !border-surface" />
      <Handle type="source" position={Position.Right} className="!w-2.5 !h-2.5 !bg-text-muted !border-surface" />
    </div>
  );
}

/* ── Zone Group Node ───────────────────────────────────── */
function ZoneNode({ data }) {
  return (
    <div className="w-full h-full relative rounded-lg" style={{ border: '2px dashed rgba(148,163,184,0.5)', minWidth: 250, minHeight: 150 }}>
      <div className="absolute -top-3 left-3 bg-surface px-2 py-0.5 rounded text-[10px] font-bold text-text-muted uppercase tracking-wider border border-border">
        {data.label || 'Zone'}
      </div>
    </div>
  );
}

const nodeTypes = { canvasService: CanvasServiceNode, zone: ZoneNode };

/* ── History helper ────────────────────────────────────── */
function useHistory() {
  const [past, setPast] = useState([]);
  const [future, setFuture] = useState([]);

  const push = useCallback((snapshot) => {
    setPast((p) => [...p.slice(-30), snapshot]);
    setFuture([]);
  }, []);

  const undo = useCallback(() => {
    let result = null;
    setPast((p) => {
      if (p.length === 0) return p;
      const copy = [...p];
      result = copy.pop();
      return copy;
    });
    if (result) setFuture((f) => [...f, result]);
    return result;
  }, []);

  const redo = useCallback(() => {
    let result = null;
    setFuture((f) => {
      if (f.length === 0) return f;
      const copy = [...f];
      result = copy.pop();
      return copy;
    });
    if (result) setPast((p) => [...p, result]);
    return result;
  }, []);

  return { past, future, push, undo, redo, canUndo: past.length > 0, canRedo: future.length > 0 };
}

/* ── Main Canvas Editor (inner, needs ReactFlowProvider) ── */
function CanvasEditorInner() {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const reactFlowInstance = useReactFlow();

  const [search, setSearch] = useState('');
  const [providerFilter, setProviderFilter] = useState('All');
  const [collapsedCategories, setCollapsedCategories] = useState({});
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);

  const history = useHistory();
  const reactFlowWrapper = useRef(null);

  // Save snapshot for undo
  const saveSnapshot = useCallback(() => {
    history.push({ nodes: nodes.map((n) => ({ ...n, data: { ...n.data } })), edges: [...edges] });
  }, [nodes, edges, history]);

  // Delete node
  const deleteNode = useCallback((nodeId) => {
    saveSnapshot();
    setNodes((nds) => nds.filter((n) => n.id !== nodeId));
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
  }, [saveSnapshot, setNodes, setEdges]);

  // Update notes on a node
  const updateNotes = useCallback((nodeId, notes) => {
    setNodes((nds) => nds.map((n) => n.id === nodeId ? { ...n, data: { ...n.data, notes } } : n));
  }, [setNodes]);

  // Filtered palette services
  const filteredServices = useMemo(() => {
    let list = SERVICES;
    if (providerFilter !== 'All') list = list.filter((s) => s.provider === providerFilter);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((s) => s.name.toLowerCase().includes(q) || s.category.toLowerCase().includes(q));
    }
    return list;
  }, [search, providerFilter]);

  // Group by category
  const groupedServices = useMemo(() => {
    const groups = {};
    for (const s of filteredServices) {
      (groups[s.category] ||= []).push(s);
    }
    return groups;
  }, [filteredServices]);

  const toggleCategory = (cat) => setCollapsedCategories((c) => ({ ...c, [cat]: !c[cat] }));

  // ── Drag & Drop from palette ────────────────────────
  const onDragStart = (event, service) => {
    event.dataTransfer.setData('application/archmorph-service', JSON.stringify(service));
    event.dataTransfer.effectAllowed = 'move';
  };

  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event) => {
      event.preventDefault();
      const raw = event.dataTransfer.getData('application/archmorph-service');
      if (!raw) return;

      const service = JSON.parse(raw);
      const bounds = reactFlowWrapper.current?.getBoundingClientRect();
      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX - (bounds?.left || 0),
        y: event.clientY - (bounds?.top || 0),
      });

      saveSnapshot();

      const newNode = {
        id: `${service.id}-${Date.now()}`,
        type: 'canvasService',
        position,
        data: {
          ...service,
          notes: '',
          onDelete: deleteNode,
          onNotesChange: updateNotes,
        },
      };
      setNodes((nds) => [...nds, newNode]);
    },
    [reactFlowInstance, saveSnapshot, deleteNode, updateNotes, setNodes],
  );

  // Keep callbacks fresh in existing nodes
  const nodesWithCallbacks = useMemo(
    () => nodes.map((n) => n.type === 'canvasService'
      ? { ...n, data: { ...n.data, onDelete: deleteNode, onNotesChange: updateNotes } }
      : n
    ),
    [nodes, deleteNode, updateNotes],
  );

  // ── Connect edges ───────────────────────────────────
  const onConnect = useCallback(
    (params) => {
      saveSnapshot();
      const newEdge = {
        ...params,
        id: `e-${params.source}-${params.target}-${Date.now()}`,
        type: 'default',
        animated: false,
        label: '',
        style: { stroke: '#64748B', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: '#64748B' },
      };
      setEdges((eds) => [...eds, newEdge]);
    },
    [saveSnapshot, setEdges],
  );

  // Edge click — toggle dashed / prompt label / delete
  const onEdgeClick = useCallback(
    (_event, edge) => {
      const action = prompt('Edge options:\n• Type a label to set it\n• Type "dashed" to toggle dashed style\n• Type "delete" to remove\n• Cancel to do nothing');
      if (action === null) return;
      saveSnapshot();
      const trimmed = action.trim().toLowerCase();
      if (trimmed === 'delete') {
        setEdges((eds) => eds.filter((e) => e.id !== edge.id));
      } else if (trimmed === 'dashed') {
        setEdges((eds) => eds.map((e) =>
          e.id === edge.id
            ? { ...e, style: { ...e.style, strokeDasharray: e.style?.strokeDasharray ? undefined : '6,4' } }
            : e
        ));
      } else if (action.trim()) {
        setEdges((eds) => eds.map((e) => e.id === edge.id ? { ...e, label: action.trim() } : e));
      }
    },
    [saveSnapshot, setEdges],
  );

  // ── Undo / Redo ────────────────────────────────────
  const handleUndo = useCallback(() => {
    const snapshot = history.undo();
    if (snapshot) {
      // Push current state to future (handled inside history.undo)
      const currentSnapshot = { nodes: nodes.map((n) => ({ ...n, data: { ...n.data } })), edges: [...edges] };
      // We already pushed to future in history.undo, just restore
      setNodes(snapshot.nodes);
      setEdges(snapshot.edges);
    }
  }, [history, nodes, edges, setNodes, setEdges]);

  const handleRedo = useCallback(() => {
    const snapshot = history.redo();
    if (snapshot) {
      setNodes(snapshot.nodes);
      setEdges(snapshot.edges);
    }
  }, [history, setNodes, setEdges]);

  // ── Add Zone ────────────────────────────────────────
  const addZone = useCallback(() => {
    const name = prompt('Zone name (e.g. VPC, Subnet, Resource Group):');
    if (!name) return;
    saveSnapshot();
    const newZone = {
      id: `zone-${Date.now()}`,
      type: 'zone',
      position: { x: 100, y: 100 },
      data: { label: name },
      style: { width: 300, height: 200 },
      draggable: true,
      selectable: true,
    };
    setNodes((nds) => [newZone, ...nds]); // zones go behind
  }, [saveSnapshot, setNodes]);

  // ── Clear All ───────────────────────────────────────
  const clearAll = useCallback(() => {
    if (!confirm('Clear all nodes and connections? This cannot be undone.')) return;
    saveSnapshot();
    setNodes([]);
    setEdges([]);
  }, [saveSnapshot, setNodes, setEdges]);

  // ── Export JSON ─────────────────────────────────────
  const exportJSON = useCallback(() => {
    const data = {
      nodes: nodes.map(({ id, type, position, data: d, style }) => ({
        id, type, position, style,
        data: { name: d.name, provider: d.provider, category: d.category, notes: d.notes, label: d.label },
      })),
      edges: edges.map(({ id, source, target, label, style }) => ({ id, source, target, label, style })),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'archmorph-canvas.json';
    a.click();
    URL.revokeObjectURL(url);
  }, [nodes, edges]);

  // ── Analyze (POST to /api/diagrams) ─────────────────
  const analyze = useCallback(async () => {
    const serviceNodes = nodes.filter((n) => n.type === 'canvasService');
    if (serviceNodes.length === 0) return;

    setAnalyzing(true);
    setAnalysisError(null);

    const payload = {
      services: serviceNodes.map((n) => ({
        name: n.data.name,
        provider: n.data.provider,
        category: n.data.category,
        notes: n.data.notes || '',
      })),
      connections: edges.map((e) => ({
        source: nodes.find((n) => n.id === e.source)?.data?.name || e.source,
        target: nodes.find((n) => n.id === e.target)?.data?.name || e.target,
        label: e.label || '',
      })),
    };

    try {
      await api(`${API_BASE}/diagrams`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setAnalyzing(false);
    } catch (err) {
      setAnalysisError(err.message || 'Analysis failed');
      setAnalyzing(false);
    }
  }, [nodes, edges]);

  // ── Service count ───────────────────────────────────
  const serviceCount = nodes.filter((n) => n.type === 'canvasService').length;

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)]">
      {/* ── Toolbar ─────────────────────────────────── */}
      <div className="flex items-center gap-2 flex-wrap mb-3 p-3 bg-primary border border-border rounded-xl">
        <Button onClick={analyze} loading={analyzing} icon={Play} size="sm" disabled={serviceCount === 0}>
          Analyze
        </Button>
        <Button onClick={addZone} variant="secondary" icon={SquareDashed} size="sm">
          Add Zone
        </Button>
        <div className="w-px h-6 bg-border mx-1" />
        <Button onClick={handleUndo} variant="ghost" icon={Undo2} size="sm" disabled={!history.canUndo} aria-label="Undo" />
        <Button onClick={handleRedo} variant="ghost" icon={Redo2} size="sm" disabled={!history.canRedo} aria-label="Redo" />
        <div className="w-px h-6 bg-border mx-1" />
        <Button onClick={exportJSON} variant="secondary" icon={Download} size="sm">
          Export JSON
        </Button>
        <Button onClick={clearAll} variant="danger" icon={Trash2} size="sm" disabled={serviceCount === 0}>
          Clear
        </Button>
        <div className="flex-1" />
        {serviceCount > 0 && (
          <Badge variant="azure">{serviceCount} service{serviceCount !== 1 ? 's' : ''}</Badge>
        )}
        {analysisError && (
          <span className="text-xs text-danger">{analysisError}</span>
        )}
      </div>

      <div className="flex flex-1 gap-3 min-h-0">
        {/* ── Service Palette (left sidebar) ────────── */}
        <aside className="w-60 shrink-0 bg-primary border border-border rounded-xl overflow-hidden flex flex-col">
          {/* Search */}
          <div className="p-2 border-b border-border">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted" />
              <input
                type="text"
                placeholder="Search services…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-7 pr-2 py-1.5 text-xs bg-secondary border border-border rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta"
              />
            </div>
          </div>

          {/* Provider filter tabs */}
          <div className="flex border-b border-border">
            {['All', ...PROVIDERS].map((p) => (
              <button
                key={p}
                onClick={() => setProviderFilter(p)}
                className={`flex-1 text-[10px] font-medium py-1.5 transition-colors cursor-pointer ${
                  providerFilter === p ? 'text-cta border-b-2 border-cta' : 'text-text-muted hover:text-text-secondary'
                }`}
              >
                {p}
              </button>
            ))}
          </div>

          {/* Service list */}
          <div className="flex-1 overflow-y-auto p-1.5 space-y-1">
            {CATEGORIES.map((cat) => {
              const items = groupedServices[cat];
              if (!items || items.length === 0) return null;
              const collapsed = collapsedCategories[cat];
              const CatIcon = CATEGORY_ICON[cat] || Server;

              return (
                <div key={cat}>
                  <button
                    onClick={() => toggleCategory(cat)}
                    className="flex items-center gap-1.5 w-full px-2 py-1 text-[10px] font-bold text-text-muted uppercase tracking-wider hover:text-text-secondary cursor-pointer"
                  >
                    {collapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                    <CatIcon className="w-3 h-3" style={{ color: CATEGORY_BORDER[cat] }} />
                    {cat}
                    <span className="ml-auto text-[9px] font-normal">{items.length}</span>
                  </button>

                  {!collapsed && (
                    <div className="space-y-0.5 ml-1">
                      {items.map((service) => (
                        <div
                          key={service.id}
                          draggable
                          onDragStart={(e) => onDragStart(e, service)}
                          className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-secondary cursor-grab active:cursor-grabbing transition-colors group"
                        >
                          <div
                            className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold text-white shrink-0"
                            style={{ backgroundColor: service.color }}
                          >
                            {service.icon_letter}
                          </div>
                          <span className="text-[11px] text-text-secondary group-hover:text-text-primary truncate flex-1">
                            {service.name}
                          </span>
                          <GripVertical className="w-3 h-3 text-text-muted opacity-0 group-hover:opacity-100" />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}

            {Object.keys(groupedServices).length === 0 && (
              <p className="text-xs text-text-muted text-center py-4">No services match your filter.</p>
            )}
          </div>
        </aside>

        {/* ── Canvas ────────────────────────────────── */}
        <div ref={reactFlowWrapper} className="flex-1 bg-primary border border-border rounded-xl overflow-hidden">
          <ReactFlow
            nodes={nodesWithCallbacks}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onEdgeClick={onEdgeClick}
            nodeTypes={nodeTypes}
            snapToGrid
            snapGrid={[16, 16]}
            fitView
            deleteKeyCode={['Backspace', 'Delete']}
            className="bg-surface"
          >
            <Background variant="dots" gap={16} size={1} className="!bg-surface" />
            <Controls
              className="!bg-primary !border-border !rounded-lg !shadow-md [&>button]:!bg-primary [&>button]:!border-border [&>button]:!text-text-secondary [&>button:hover]:!bg-secondary"
              showInteractive={false}
            />
            <MiniMap
              className="!bg-primary !border-border !rounded-lg"
              nodeColor={(n) => CATEGORY_BORDER[n.data?.category] || '#64748B'}
              maskColor="rgba(0,0,0,0.15)"
            />
          </ReactFlow>
        </div>
      </div>
    </div>
  );
}

/* ── Wrapper with Provider ─────────────────────────────── */
export default function CanvasEditor() {
  return (
    <ReactFlowProvider>
      <CanvasEditorInner />
    </ReactFlowProvider>
  );
}
