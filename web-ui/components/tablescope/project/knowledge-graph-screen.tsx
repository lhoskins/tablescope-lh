"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { IconDownload, IconMaximize, IconShare, IconTopologyStar3 } from "@tabler/icons-react";
import {
  useKnowledgeGraph,
  type GraphId,
  type GraphNode,
  type KnowledgeGraphInsightCard,
} from "@/lib/ui/use-project-data";
import { KnowledgeGraphControls } from "./knowledge-graph-controls";
import { KnowledgeGraphCanvas } from "./knowledge-graph-canvas";
import { KnowledgeGraphInsightPanel } from "./knowledge-graph-insight-panel";
import { humanize } from "./knowledge-graph-style";

interface ScreenProps {
  projectId: number;
  /** Optional breadcrumb context (e.g. document family name). */
  breadcrumb?: string[];
}

export function KnowledgeGraphScreen({ projectId, breadcrumb }: ScreenProps) {
  const [lens, setLens] = useState("insight-first");
  const [centerNode, setCenterNode] = useState<string | null>(null);
  const [minConfidence, setMinConfidence] = useState(0.7);
  const [includeInferred, setIncludeInferred] = useState(false);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [highestFirst, setHighestFirst] = useState(true);
  const [tracingCardId, setTracingCardId] = useState<string | null>(null);
  const [tracedNodeIds, setTracedNodeIds] = useState<Set<GraphId> | null>(null);

  // Hydrate center/lens from the URL once (shareable deep links).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const sp = new URLSearchParams(window.location.search);
    const c = sp.get("center_node");
    const l = sp.get("lens");
    if (c) setCenterNode(c);
    if (l) setLens(l);
  }, []);

  const query = useKnowledgeGraph(String(projectId), {
    lens,
    centerNode,
    minConfidence,
    includeInferred,
  });
  const data = query.data;

  const handleNodeClick = useCallback((node: GraphNode) => {
    if (!node.graphKey) return;
    setCenterNode(node.graphKey);
    if (node.recommendedLens) setLens(node.recommendedLens);
    setTracingCardId(null);
    setTracedNodeIds(null);
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      sp.set("center_node", node.graphKey);
      sp.set("lens", node.recommendedLens || lens);
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}?${sp.toString()}`,
      );
    }
  }, [lens]);

  const handleTrace = useCallback((card: KnowledgeGraphInsightCard) => {
    setTracingCardId((prev) => {
      if (prev === card.id) {
        setTracedNodeIds(null);
        return null;
      }
      setTracedNodeIds(new Set(card.traceToEvidence.nodeIds));
      return card.id;
    });
  }, []);

  const handleReset = useCallback(() => {
    setLens("insight-first");
    setMinConfidence(0.7);
    setIncludeInferred(false);
    setHiddenTypes(new Set());
    setHighestFirst(true);
    setTracingCardId(null);
    setTracedNodeIds(null);
  }, []);

  const toggleType = useCallback((type: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }, []);

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of data?.nodes ?? []) {
      counts.set(n.type, (counts.get(n.type) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([type, count]) => ({ type, count }))
      .sort((a, b) => b.count - a.count);
  }, [data?.nodes]);

  // Client-side node-type filtering (keeps the center node visible).
  const visibleNodes = useMemo(() => {
    if (!data) return [];
    return data.nodes.filter(
      (n) => n.id === data.centerNode?.id || !hiddenTypes.has(n.type),
    );
  }, [data, hiddenTypes]);

  const visibleNodeIds = useMemo(
    () => new Set(visibleNodes.map((n) => n.id)),
    [visibleNodes],
  );

  const visibleEdges = useMemo(() => {
    if (!data) return [];
    const edges = data.edges.filter(
      (e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target),
    );
    if (highestFirst) {
      return [...edges].sort((a, b) => b.confidence - a.confidence);
    }
    return edges;
  }, [data, visibleNodeIds, highestFirst]);

  const center = data?.centerNode ?? null;
  const title = center?.label ?? "Knowledge Graph";
  const crumbs = breadcrumb ?? ["Documents", "Knowledge Graph"];

  return (
    <div className="flex h-[calc(100vh-220px)] min-h-[640px] gap-3">
      {/* Left controls */}
      <aside className="w-[252px] shrink-0 rounded-lg border border-line-tertiary bg-bg-primary">
        <KnowledgeGraphControls
          lens={lens}
          onLensChange={setLens}
          minConfidence={minConfidence}
          onMinConfidenceChange={setMinConfidence}
          includeInferred={includeInferred}
          onIncludeInferredChange={setIncludeInferred}
          typeCounts={typeCounts}
          hiddenTypes={hiddenTypes}
          onToggleType={toggleType}
          highestFirst={highestFirst}
          onHighestFirstChange={setHighestFirst}
          onReset={handleReset}
        />
      </aside>

      {/* Center canvas */}
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="mb-2 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <nav className="flex items-center gap-1 text-small text-ink-tertiary">
              {crumbs.map((c, i) => (
                <span key={i} className="flex items-center gap-1">
                  {i > 0 && <span>/</span>}
                  <span className={i === crumbs.length - 1 ? "text-ink-secondary" : ""}>
                    {c}
                  </span>
                </span>
              ))}
            </nav>
            <h1 className="truncate text-h2 text-ink-primary">{title}</h1>
            {center && (
              <p className="text-small text-ink-tertiary">
                {humanize(center.type)} · {lens} lens · {data?.stats.nodeCount ?? 0}{" "}
                nodes · {data?.stats.edgeCount ?? 0} edges
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1.5 text-ink-tertiary">
            <button type="button" className="rounded-md border border-line-tertiary p-1.5 hover:bg-bg-tertiary" title="Export">
              <IconDownload size={16} />
            </button>
            <button type="button" className="rounded-md border border-line-tertiary p-1.5 hover:bg-bg-tertiary" title="Share">
              <IconShare size={16} />
            </button>
            <button type="button" className="rounded-md border border-line-tertiary p-1.5 hover:bg-bg-tertiary" title="Fullscreen">
              <IconMaximize size={16} />
            </button>
          </div>
        </header>

        {query.isLoading ? (
          <div className="flex flex-1 items-center justify-center rounded-lg border border-line-tertiary text-small text-ink-tertiary">
            Building knowledge graph…
          </div>
        ) : query.isError ? (
          <div className="flex flex-1 items-center justify-center rounded-lg border border-line-tertiary text-small text-danger">
            Failed to load the knowledge graph.
          </div>
        ) : !center || visibleNodes.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center rounded-lg border border-line-tertiary text-center text-ink-tertiary">
            <IconTopologyStar3 size={40} className="mb-3 text-line-secondary" />
            <p className="text-body">No knowledge graph data yet</p>
            <p className="mt-1 text-small">
              Upload documents and process them with AI to build the project
              knowledge graph.
            </p>
          </div>
        ) : (
          <div className="min-h-0 flex-1">
            <KnowledgeGraphCanvas
              centerNode={center}
              nodes={visibleNodes}
              edges={visibleEdges}
              selectedNodeKey={centerNode}
              tracedNodeIds={tracedNodeIds}
              onNodeClick={handleNodeClick}
            />
          </div>
        )}
      </section>

      {/* Right insight panel */}
      <aside className="w-[372px] shrink-0 rounded-lg border border-line-tertiary bg-bg-primary">
        <KnowledgeGraphInsightPanel
          title={center ? center.label : "Knowledge Graph"}
          subtitle="Business insight"
          cards={data?.insightCards ?? []}
          tracingCardId={tracingCardId}
          onTrace={handleTrace}
        />
      </aside>
    </div>
  );
}
