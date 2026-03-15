import React, { useMemo } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  applyNodeChanges,
  applyEdgeChanges,
  Handle,
  Position,
} from '@xyflow/react';
import dagre from 'dagre';
import '@xyflow/react/dist/style.css';

import {
  FaAws
} from 'react-icons/fa';

import {
  VscAzure
} from 'react-icons/vsc';

import {
  SiGooglecloud
} from 'react-icons/si';

import { 
  ArrowRight,
  Database,
  Server,
  Zap,
  HardDrive
} from 'lucide-react';

const NODE_WIDTH = 250;
const NODE_HEIGHT = 80;

const getCloudIcon = (serviceName, defaultIcon) => {
  if (!serviceName) return defaultIcon;
  const s = serviceName.toLowerCase();
  if (s.includes('lambda') || s.includes('functions')) return <Zap className="w-5 h-5 text-gray-500" />;
  if (s.includes('ec2') || s.includes('compute')) return <Server className="w-5 h-5 text-gray-500" />;
  if (s.includes('s3') || s.includes('blob')) return <HardDrive className="w-5 h-5 text-gray-500" />;
  if (s.includes('rds') || s.includes('cosmos')) return <Database className="w-5 h-5 text-gray-500" />;
  return defaultIcon;
};

// Custom Node for displaying mapped services
function MappingNode({ data }) {
  const { source, target, provider } = data;

  const pLower = (provider || 'aws').toLowerCase();
  const PIcon = pLower === 'gcp'
    ? <SiGooglecloud className="w-5 h-5 text-[#EA4335]" />
    : <FaAws className="w-5 h-5 text-[#FF9900]" />;

  return (
    <div className="bg-card border-2 border-border rounded-lg shadow-md p-3 flex flex-col gap-2 min-w-[220px]">
      <Handle type="target" position={Position.Top} className="w-3 h-3 bg-secondary" />
      
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-col items-center gap-1 w-[40%]" title={source}>
          {getCloudIcon(source, PIcon)}
          <span className="text-[10px] font-medium text-text-secondary text-center leading-tight truncate w-full">
            {source}
          </span>
        </div>
        
        <ArrowRight className="w-4 h-4 text-text-muted flex-shrink-0" />

        <div className="flex flex-col items-center gap-1 w-[40%]" title={target}>
          {getCloudIcon(target, <VscAzure className="w-5 h-5 text-[#0089D6]" />)}
          <span className="text-[10px] font-bold text-text-primary text-center leading-tight truncate w-full">
            {target || 'Pending'}
          </span>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="w-3 h-3 bg-primary" />
    </div>
  );
}

function GroupNode({ data }) {
  return (
    <div className="w-full h-full relative" style={{ zIndex: -1 }}>
      <div className="absolute top-2 left-3 bg-white/70 px-2 py-1 rounded-md text-xs font-semibold text-primary border border-border shadow-sm">
        {data.label}
      </div>
    </div>
  );
}

const nodeTypes = {
  mappingNode: MappingNode,
  groupNode: GroupNode,
};

// Layout engine
const getLayoutedElements = (nodes, edges) => {
  const dagreGraph = new dagre.graphlib.Graph({ compound: true });
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  
  dagreGraph.setGraph({ rankdir: 'TB', ranksep: 80, nodesep: 60 });

  nodes.forEach((node) => {
    if (node.type === 'group') {
      dagreGraph.setNode(node.id, { label: node.data.label, clusterLabelPos: 'top' });
    } else {
      dagreGraph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    }
    if (node.parentId) {
      dagreGraph.setParent(node.id, node.parentId);
    }
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  nodes.forEach((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    node.targetPosition = 'top';
    node.sourcePosition = 'bottom';
    
    let x = nodeWithPosition.x - nodeWithPosition.width / 2;
    let y = nodeWithPosition.y - nodeWithPosition.height / 2;

    if (node.type === 'group' || node.type === 'groupNode') {
      const gWidth = (nodeWithPosition.width || NODE_WIDTH) + 40;
      const gHeight = (nodeWithPosition.height || NODE_HEIGHT) + 60;
      node.style = { ...node.style, width: gWidth, height: gHeight };
      x -= 20; 
      y -= 40; 
    }

    if (node.parentId) {
      const parentWithPosition = dagreGraph.node(node.parentId);
      const parentX = parentWithPosition.x - (parentWithPosition.width || 0) / 2 - 20;
      const parentY = parentWithPosition.y - (parentWithPosition.height || 0) / 2 - 40;
      x -= parentX;
      y -= parentY;
    }
    
    node.position = { x, y };
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
    
    // Create group nodes for each zone
    zones.forEach((zone) => {
      nodes.push({
        id: `zone-${zone.name}`,
        type: 'groupNode',
        data: { label: zone.name },
        position: { x: 0, y: 0 },
        style: {
          backgroundColor: 'rgba(240, 247, 255, 0.4)',
          border: '1px dashed #527FFF',
          borderRadius: '8px',
          zIndex: -1
        },
      });
    });

    // Create a node for each mapping
    // We use source_service name as ID to link edges correctly
    mappings.forEach((m) => {
      if (m.azure_service && m.azure_service !== '[Manual mapping needed]') {
        const parentZone = zones.find(z => z.services?.includes(m.source_service));
        nodes.push({
          id: m.source_service,
          type: 'mappingNode',
          parentId: parentZone ? `zone-${parentZone.name}` : undefined,
          extent: parentZone ? 'parent' : undefined,
          data: {
            source: m.source_service,
            target: m.azure_service,
            provider: analysis?.source_provider || m.source_provider || 'aws'
          },
          position: { x: 0, y: 0 } // Computed by dagre
        });
      }
    });

    // Create edges
    connections.forEach((conn, idx) => {
      // only add if both nodes exist in mapped nodes
      if (nodes.find(n => n.id === conn.from) && nodes.find(n => n.id === conn.to)) {
        edges.push({
          id: `e${idx}-${conn.from}-${conn.to}`,
          source: conn.from,
          target: conn.to,
          animated: true,
          label: conn.protocol || '',
          style: { stroke: '#527FFF', strokeWidth: 2 },
          labelStyle: { fill: '#888', fontWeight: 500, fontSize: 10 },
          labelBgStyle: { fill: 'transparent' }
        });
      }
    });

    // Fallback if there are no connections but there are nodes
    if (nodes.length && edges.length === 0) {
      // Try to connect them sequentially if it makes sense, 
      // or just let dagre place them side by side
    }

    const layouted = getLayoutedElements(nodes, edges);
    return { initialNodes: layouted.nodes, initialEdges: layouted.edges };
  }, [analysis]);

  const [nodes, setNodes] = React.useState(initialNodes);
  const [edges, setEdges] = React.useState(initialEdges);

  React.useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges]);

  const onNodesChange = React.useCallback(
    (changes) => setNodes((nds) => applyNodeChanges(changes, nds)),
    []
  );
  const onEdgesChange = React.useCallback(
    (changes) => setEdges((eds) => applyEdgeChanges(changes, eds)),
    []
  );

  if (!nodes.length) {
    return (
      <div className="w-full h-64 flex items-center justify-center text-text-muted bg-secondary/20 rounded-lg border border-border">
        No architecture diagram data available.
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '500px' }} className="rounded-lg border border-border overflow-hidden bg-background/50">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-right"
      >
        <Background color="#777" gap={16} size={1} />
        <Controls />
      </ReactFlow>
    </div>
  );
}
