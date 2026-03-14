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
  SiAmazonwebservices,
  SiGooglecloud,
  SiMicrosoftazure,
  SiAwslambda,
  SiAmazonec2,
  SiAmazons3,
  SiAmazonrds,
  SiAzurefunctions,
  SiAzuredevops,
} from 'react-icons/si';

import { ArrowRight } from 'lucide-react';

const NODE_WIDTH = 250;
const NODE_HEIGHT = 80;

const getCloudIcon = (serviceName, defaultIcon) => {
  if (!serviceName) return defaultIcon;
  const s = serviceName.toLowerCase();
  if (s.includes('lambda')) return <SiAwslambda className="w-5 h-5 text-[#FF9900]" />;
  if (s.includes('ec2')) return <SiAmazonec2 className="w-5 h-5 text-[#FF9900]" />;
  if (s.includes('s3')) return <SiAmazons3 className="w-5 h-5 text-[#569A31]" />;
  if (s.includes('rds')) return <SiAmazonrds className="w-5 h-5 text-[#527FFF]" />;
  if (s.includes('functions')) return <SiAzurefunctions className="w-5 h-5 text-[#0062AD]" />;
  return defaultIcon;
};

// Custom Node for displaying mapped services
function MappingNode({ data }) {
  const { source, target, provider } = data;

  const pLower = (provider || 'aws').toLowerCase();
  const PIcon = pLower === 'gcp'
    ? <SiGooglecloud className="w-5 h-5 text-[#EA4335]" />
    : <SiAmazonwebservices className="w-5 h-5 text-[#FF9900]" />;

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
          {getCloudIcon(target, <SiMicrosoftazure className="w-5 h-5 text-[#0089D6]" />)}
          <span className="text-[10px] font-bold text-text-primary text-center leading-tight truncate w-full">
            {target || 'Pending'}
          </span>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="w-3 h-3 bg-primary" />
    </div>
  );
}

const nodeTypes = {
  mappingNode: MappingNode,
};

// Layout engine
const getLayoutedElements = (nodes, edges) => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  
  dagreGraph.setGraph({ rankdir: 'TB', ranksep: 80, nodesep: 60 });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  nodes.forEach((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    node.targetPosition = 'top';
    node.sourcePosition = 'bottom';
    // Dagre sets center points, React Flow needs top-left
    node.position = {
      x: nodeWithPosition.x - nodeWithPosition.width / 2,
      y: nodeWithPosition.y - nodeWithPosition.height / 2,
    };
  });

  return { nodes, edges };
};

export default function ArchitectureFlow({ analysis }) {
  const { initialNodes, initialEdges } = useMemo(() => {
    const mappings = analysis?.mappings || [];
    const connections = analysis?.service_connections || [];

    const nodes = [];
    const edges = [];
    
    // Create a node for each mapping
    // We use source_service name as ID to link edges correctly
    mappings.forEach((m) => {
      if (m.azure_service && m.azure_service !== '[Manual mapping needed]') {
        nodes.push({
          id: m.source_service,
          type: 'mappingNode',
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

    return getLayoutedElements(nodes, edges);
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
