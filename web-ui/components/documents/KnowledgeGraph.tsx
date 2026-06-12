"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

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

// ── Styling ────────────────────────────────────────────────────────

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

// Friendly group headings keyed by edge type (fallback: humanized type).
const EDGE_GROUP_LABELS: Record<string, string> = {
  has_tag: "Tags",
  supports_kpi: "KPIs",
  related_to_datasource: "Datasources",
  contains_entity: "Entities",
  references: "References",
  related_to: "Related",
};

function humanize(text: string): string {
  return text.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function colorsFor(type: string) {
  return NODE_COLORS[type] ?? NODE_COLORS.default;
}

function iconFor(type: string) {
  return NODE_ICONS[type] ?? "●";
}

// ── Derived tree structures ────────────────────────────────────────

type ChildLink = {
  edgeId: number;
  groupKey: string;
  groupLabel: string;
  node: GraphNode;
  confidence: number;
  evidence: string;
};

type DocBranch = {
  doc: GraphNode;
  groups: { key: string; label: string; children: ChildLink[] }[];
  total: number;
};

function buildTree(nodes: GraphNode[], edges: GraphEdge[]) {
  const nodeById = new Map<number, GraphNode>();
  for (const n of nodes) nodeById.set(n.id, n);

  const documents = nodes
    .filter((n) => n.type === "document")
    .sort((a, b) => a.label.localeCompare(b.label));

  const linkedNodeIds = new Set<number>();

  const branches: DocBranch[] = documents.map((doc) => {
    // Any edge that touches this document; the "other" endpoint is the child.
    const links: ChildLink[] = [];
    for (const e of edges) {
      let otherId: number | null = null;
      if (e.source === doc.id) otherId = e.target;
      else if (e.target === doc.id) otherId = e.source;
      if (otherId === null) continue;

      const other = nodeById.get(otherId);
      if (!other || other.type === "document") continue;

      linkedNodeIds.add(other.id);
      const groupKey = e.type;
      links.push({
        edgeId: e.id,
        groupKey,
        groupLabel: EDGE_GROUP_LABELS[groupKey] ?? humanize(groupKey),
        node: other,
        confidence: e.confidence,
        evidence: e.evidence,
      });
    }

    // Group links by edge type, sort children by confidence desc.
    const byGroup = new Map<string, ChildLink[]>();
    for (const l of links) {
      const arr = byGroup.get(l.groupKey) ?? [];
      arr.push(l);
      byGroup.set(l.groupKey, arr);
    }
    const groups = [...byGroup.entries()]
      .map(([key, children]) => ({
        key,
        label: children[0]?.groupLabel ?? humanize(key),
        children: children.sort((a, b) => b.confidence - a.confidence),
      }))
      .sort((a, b) => a.label.localeCompare(b.label));

    return { doc, groups, total: links.length };
  });

  // Non-document nodes that aren't linked to any document.
  const orphans = nodes.filter(
    (n) => n.type !== "document" && !linkedNodeIds.has(n.id),
  );
  const orphansByType = new Map<string, GraphNode[]>();
  for (const n of orphans) {
    const arr = orphansByType.get(n.type) ?? [];
    arr.push(n);
    orphansByType.set(n.type, arr);
  }

  return { branches, orphansByType, documentCount: documents.length };
}

// ── Small UI pieces ────────────────────────────────────────────────

function TypeBadge({ type }: { type: string }) {
  const c = colorsFor(type);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium border"
      style={{ backgroundColor: c.bg, borderColor: c.border, color: c.text }}
    >
      {iconFor(type)} {type}
    </span>
  );
}

function CountChip({ label, count, type }: { label: string; count: number; type: string }) {
  const c = colorsFor(type);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium border"
      style={{ backgroundColor: c.bg, borderColor: c.border, color: c.text }}
    >
      {count} {label}
    </span>
  );
}

// Map a group to the node type it mostly contains, for chip coloring.
function groupType(children: ChildLink[]): string {
  return children[0]?.node.type ?? "default";
}

// ── Main component ─────────────────────────────────────────────────

export function KnowledgeGraph({ projectId }: { projectId: number }) {
  const graphQuery = useQuery<GraphResponse>({
    queryKey: ["project-graph", projectId],
    queryFn: () => apiClient.get(`/api/projects/${projectId}/graph`),
  });

  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [showOrphans, setShowOrphans] = useState(false);

  const tree = useMemo(() => {
    if (!graphQuery.data) return null;
    return buildTree(graphQuery.data.nodes, graphQuery.data.edges);
  }, [graphQuery.data]);

  const toggle = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const expandAll = () => {
    if (!tree) return;
    setExpanded(new Set(tree.branches.map((b) => b.doc.id)));
  };
  const collapseAll = () => setExpanded(new Set());

  if (graphQuery.isLoading) {
    return <div className="text-sm text-slate-400 py-8 text-center">Loading knowledge graph...</div>;
  }

  if (!graphQuery.data || graphQuery.data.nodes.length === 0 || !tree) {
    return (
      <div className="py-12 text-center text-slate-400">
        <p className="text-4xl mb-3">🕸️</p>
        <p className="text-sm">No knowledge graph data yet</p>
        <p className="text-xs mt-1">
          Upload documents and process them with AI to build the project knowledge graph
        </p>
      </div>
    );
  }

  const { nodes, edges } = graphQuery.data;
  const orphanTypes = [...tree.orphansByType.keys()];

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-slate-500">
          {tree.documentCount} documents · {nodes.length} nodes · {edges.length} edges
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={expandAll}
            className="rounded-md border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            Expand all
          </button>
          <button
            type="button"
            onClick={collapseAll}
            className="rounded-md border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            Collapse all
          </button>
        </div>
      </div>

      {/* Document branches */}
      <div className="space-y-2">
        {tree.branches.map((branch) => {
          const isOpen = expanded.has(branch.doc.id);
          const c = colorsFor("document");
          return (
            <div key={branch.doc.id} className="rounded-lg border border-slate-200 bg-white">
              {/* Document header row */}
              <button
                type="button"
                onClick={() => toggle(branch.doc.id)}
                className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-slate-50"
              >
                <span className="text-slate-400 text-xs w-3">{isOpen ? "▾" : "▸"}</span>
                <span className="text-base">{iconFor("document")}</span>
                <span className="text-sm font-semibold truncate" style={{ color: c.text }}>
                  {branch.doc.label}
                </span>
                <div className="ml-auto flex flex-wrap items-center gap-1">
                  {branch.groups.length === 0 ? (
                    <span className="text-[10px] text-slate-400">no connections</span>
                  ) : (
                    branch.groups.map((g) => (
                      <CountChip
                        key={g.key}
                        label={g.label}
                        count={g.children.length}
                        type={groupType(g.children)}
                      />
                    ))
                  )}
                </div>
              </button>

              {/* Expanded children grouped by relationship */}
              {isOpen && branch.groups.length > 0 && (
                <div className="border-t border-slate-100 px-3 py-2 space-y-3">
                  {branch.groups.map((g) => (
                    <div key={g.key}>
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">
                        {g.label} ({g.children.length})
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {g.children.map((child) => {
                          const cc = colorsFor(child.node.type);
                          return (
                            <span
                              key={`${g.key}-${child.edgeId}`}
                              title={child.evidence || undefined}
                              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs border"
                              style={{ backgroundColor: cc.bg, borderColor: cc.border, color: cc.text }}
                            >
                              <span>{iconFor(child.node.type)}</span>
                              <span className="font-medium">{child.node.label}</span>
                              <span className="text-[10px] opacity-60">
                                {Math.round(child.confidence * 100)}%
                              </span>
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Unlinked nodes (tags/KPIs/etc. not attached to a document) */}
      {orphanTypes.length > 0 && (
        <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/50">
          <button
            type="button"
            onClick={() => setShowOrphans((s) => !s)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-slate-500 hover:bg-slate-100/50"
          >
            <span className="w-3">{showOrphans ? "▾" : "▸"}</span>
            <span className="font-semibold">Unlinked nodes</span>
            <span className="text-slate-400">
              ({[...tree.orphansByType.values()].reduce((s, a) => s + a.length, 0)})
            </span>
          </button>
          {showOrphans && (
            <div className="border-t border-slate-200 px-3 py-2 space-y-3">
              {orphanTypes.map((t) => (
                <div key={t}>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">
                    {humanize(t)} ({tree.orphansByType.get(t)!.length})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {tree.orphansByType.get(t)!.map((n) => {
                      const cc = colorsFor(n.type);
                      return (
                        <span
                          key={n.id}
                          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs border"
                          style={{ backgroundColor: cc.bg, borderColor: cc.border, color: cc.text }}
                        >
                          <span>{iconFor(n.type)}</span>
                          <span className="font-medium">{n.label}</span>
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <span className="text-[10px] font-semibold text-slate-400">Legend:</span>
        {[...new Set(nodes.map((n) => n.type))].map((t) => (
          <TypeBadge key={t} type={t} />
        ))}
      </div>
    </div>
  );
}
