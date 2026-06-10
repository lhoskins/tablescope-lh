"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  type Node,
  type Edge,
  type NodeTypes,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

// ── Types ──────────────────────────────────────────────────────────

type GraphNode = {
  id: number;
  type: string;
  label: string;
  source_type: string | null;
  source_id: number | null;
  properties: Record<string, unknown>;
};

type GraphEdge = {
  id: number;
  source: number;
  target: number;
  type: string;
  confidence: number;
  evidence: string;
};

type GraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

// ── Node colors ────────────────────────────────────────────────────

const NODE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  document: { bg: "#EFF6FF", border: "#3B82F6", text: "#1E40AF" },
  tag: { bg: "#F0FDF4", border: "#22C55E", text: "#166534" },
  kpi: { bg: "#FFFBEB", border: "#F59E0B", text: "#92400E" },
  entity: { bg: "#FDF2F8", border: "#EC4899", text: "#9D174D" },
  supplier: { bg: "#FDF2F8", border: "#EC4899", text: "#9D174D" },
  customer: { bg: "#FDF2F8", border: "#EC4899", text: "#9D174D" },
  product: { bg: "#F5F3FF", border: "#8B5CF6", text: "#5B21B6" },
  process: { bg: "#FFF7ED", border: "#F97316", text: "#9A3412" },
  risk: { bg: "#FEF2F2", border: "#EF4444", text: "#991B1B" },
  datasource: { bg: "#ECFDF5", border: "#10B981", text: "#065F46" },
  default: { bg: "#F8FAFC", border: "#94A3B8", text: "#334155" },
};

const NODE_ICONS: Record<string, string> = {
  document: "📄",
  tag: "🏷️",
  kpi: "📊",
  entity: "🏢",
  supplier: "🏭",
  customer: "👤",
  product: "📦",
  process: "⚙️",
  risk: "⚠️",
  datasource: "💾",
  action: "▶️",
};

// ── Custom node component ──────────────────────────────────────────

function GraphNodeComponent({ data }: { data: { label: string; nodeType: string; properties: Record<string, unknown> } }) {
  const colors = NODE_COLORS[data.nodeType] ?? NODE_COLORS.default;
  const icon = NODE_ICONS[data.nodeType] ?? "●";

  return (
    <>
      <Handle type="target" position={Position.Top} style={{ background: colors.border, width: 6, height: 6 }} />
      <div
        className="rounded-lg px-3 py-2 shadow-sm border-2 text-center max-w-[180px]"
        style={{ backgroundColor: colors.bg, borderColor: colors.border }}
      >
        <div className="text-base mb-0.5">{icon}</div>
        <div className="text-xs font-semibold truncate" style={{ color: colors.text }}>
          {data.label}
        </div>
        <div className="text-[9px] uppercase mt-0.5" style={{ color: colors.text, opacity: 0.6 }}>
          {data.nodeType}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: colors.border, width: 6, height: 6 }} />
    </>
  );
}

const nodeTypes: NodeTypes = {
  graphNode: GraphNodeComponent,
};

// ── Force-directed layout ──────────────────────────────────────────

function layoutNodes(graphNodes: GraphNode[], graphEdges: GraphEdge[]): Node[] {
  if (graphNodes.length === 0) return [];

  // Group nodes by type for radial layout
  const groups: Record<string, GraphNode[]> = {};
  for (const n of graphNodes) {
    const t = n.type;
    if (!groups[t]) groups[t] = [];
    groups[t].push(n);
  }

  const typeOrder = ["document", "datasource", "tag", "kpi", "entity", "supplier", "customer", "product", "process", "risk", "action"];
  const sortedTypes = Object.keys(groups).sort((a, b) => {
    const ai = typeOrder.indexOf(a);
    const bi = typeOrder.indexOf(b);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  const nodes: Node[] = [];
  const centerX = 500;
  const centerY = 400;

  // Documents in center, other types in rings
  const docNodes = groups["document"] ?? [];
  const otherTypes = sortedTypes.filter((t) => t !== "document");

  // Place document nodes in center cluster
  const docSpacing = 220;
  const docCols = Math.ceil(Math.sqrt(docNodes.length));
  docNodes.forEach((n, i) => {
    const col = i % docCols;
    const row = Math.floor(i / docCols);
    const x = centerX + (col - docCols / 2) * docSpacing;
    const y = centerY + (row - Math.floor(docNodes.length / docCols) / 2) * docSpacing;
    nodes.push({
      id: String(n.id),
      type: "graphNode",
      position: { x, y },
      data: { label: n.label, nodeType: n.type, properties: n.properties },
    });
  });

  // Place other nodes in concentric rings
  let ringRadius = 350;
  for (const t of otherTypes) {
    const group = groups[t];
    const angleStep = (2 * Math.PI) / Math.max(group.length, 1);
    const startAngle = Math.random() * Math.PI * 0.5; // slight randomization

    group.forEach((n, i) => {
      const angle = startAngle + i * angleStep;
      const jitter = (Math.random() - 0.5) * 40;
      const x = centerX + (ringRadius + jitter) * Math.cos(angle);
      const y = centerY + (ringRadius + jitter) * Math.sin(angle);
      nodes.push({
        id: String(n.id),
        type: "graphNode",
        position: { x, y },
        data: { label: n.label, nodeType: n.type, properties: n.properties },
      });
    });

    ringRadius += 180 + group.length * 15;
  }

  return nodes;
}

function layoutEdges(graphEdges: GraphEdge[]): Edge[] {
  return graphEdges.map((e) => ({
    id: `e-${e.id}`,
    source: String(e.source),
    target: String(e.target),
    label: e.type.replace(/_/g, " "),
    type: "default",
    animated: e.confidence >= 0.8,
    style: {
      stroke: e.confidence >= 0.8 ? "#3B82F6" : "#94A3B8",
      strokeWidth: Math.max(1, Math.min(3, e.confidence * 3)),
    },
    labelStyle: { fontSize: 9, fill: "#64748B" },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 12,
      height: 12,
      color: e.confidence >= 0.8 ? "#3B82F6" : "#94A3B8",
    },
  }));
}

// ── Main component ─────────────────────────────────────────────────

export function KnowledgeGraph({ projectId }: { projectId: number }) {
  const graphQuery = useQuery<GraphResponse>({
    queryKey: ["project-graph", projectId],
    queryFn: () => apiClient.get(`/api/projects/${projectId}/graph`),
  });

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const initialNodes = useMemo(() => {
    if (!graphQuery.data) return [];
    return layoutNodes(graphQuery.data.nodes, graphQuery.data.edges);
  }, [graphQuery.data]);

  const initialEdges = useMemo(() => {
    if (!graphQuery.data) return [];
    return layoutEdges(graphQuery.data.edges);
  }, [graphQuery.data]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const gNode = graphQuery.data?.nodes.find((n) => String(n.id) === node.id);
      setSelectedNode(gNode ?? null);
    },
    [graphQuery.data],
  );

  if (graphQuery.isLoading) {
    return <div className="text-sm text-slate-400 py-8 text-center">Loading knowledge graph...</div>;
  }

  if (!graphQuery.data || graphQuery.data.nodes.length === 0) {
    return (
      <div className="py-12 text-center text-slate-400">
        <p className="text-4xl mb-3">🕸️</p>
        <p className="text-sm">No knowledge graph data yet</p>
        <p className="text-xs mt-1">Upload documents and process them with AI to build the project knowledge graph</p>
      </div>
    );
  }

  // Legend
  const typesPresent = [...new Set(graphQuery.data.nodes.map((n) => n.type))];

  return (
    <div className="space-y-3">
      {/* Legend */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-xs font-semibold text-slate-500 mr-1">Legend:</span>
        {typesPresent.map((t) => {
          const colors = NODE_COLORS[t] ?? NODE_COLORS.default;
          const icon = NODE_ICONS[t] ?? "●";
          return (
            <span
              key={t}
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium border"
              style={{ backgroundColor: colors.bg, borderColor: colors.border, color: colors.text }}
            >
              {icon} {t}
            </span>
          );
        })}
        <span className="text-[10px] text-slate-400 ml-2">
          {graphQuery.data.nodes.length} nodes · {graphQuery.data.edges.length} edges
        </span>
      </div>

      {/* Graph */}
      <div className="rounded-lg border border-slate-200 bg-white" style={{ height: 600 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.2}
          maxZoom={2}
          defaultEdgeOptions={{ type: "default" }}
        >
          <Background gap={20} size={1} color="#E2E8F0" />
          <Controls showInteractive={false} />
          <MiniMap
            nodeStrokeWidth={3}
            nodeColor={(n) => {
              const t = (n.data as Record<string, unknown>)?.nodeType as string | undefined;
              return (NODE_COLORS[t ?? ""] ?? NODE_COLORS.default).border;
            }}
          />
        </ReactFlow>
      </div>

      {/* Selected node detail panel */}
      {selectedNode && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-lg">{NODE_ICONS[selectedNode.type] ?? "●"}</span>
              <h3 className="text-sm font-semibold text-slate-900">{selectedNode.label}</h3>
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-medium border"
                style={{
                  backgroundColor: (NODE_COLORS[selectedNode.type] ?? NODE_COLORS.default).bg,
                  borderColor: (NODE_COLORS[selectedNode.type] ?? NODE_COLORS.default).border,
                  color: (NODE_COLORS[selectedNode.type] ?? NODE_COLORS.default).text,
                }}
              >
                {selectedNode.type}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setSelectedNode(null)}
              className="text-slate-400 hover:text-slate-600"
            >
              ✕
            </button>
          </div>
          {selectedNode.properties && Object.keys(selectedNode.properties).length > 0 && (
            <div className="space-y-1">
              {Object.entries(selectedNode.properties).map(([key, value]) => (
                <div key={key} className="flex gap-2 text-xs">
                  <span className="text-slate-400 font-medium min-w-[100px]">{key}:</span>
                  <span className="text-slate-600">{String(value)}</span>
                </div>
              ))}
            </div>
          )}
          {/* Connected edges */}
          <div className="mt-3 pt-3 border-t border-slate-100">
            <h4 className="text-[10px] font-semibold text-slate-400 uppercase mb-1">Connections</h4>
            <div className="space-y-1">
              {graphQuery.data.edges
                .filter((e) => e.source === selectedNode.id || e.target === selectedNode.id)
                .map((e) => {
                  const otherNodeId = e.source === selectedNode.id ? e.target : e.source;
                  const otherNode = graphQuery.data?.nodes.find((n) => n.id === otherNodeId);
                  const direction = e.source === selectedNode.id ? "→" : "←";
                  return (
                    <div key={e.id} className="flex items-center gap-1 text-xs text-slate-600">
                      <span>{direction}</span>
                      <span className="text-slate-400">{e.type.replace(/_/g, " ")}</span>
                      <span className="font-medium">{otherNode?.label ?? `Node #${otherNodeId}`}</span>
                      <span className="text-[10px] text-slate-300">
                        ({Math.round(e.confidence * 100)}%)
                      </span>
                    </div>
                  );
                })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
