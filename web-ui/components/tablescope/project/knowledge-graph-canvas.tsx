"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  IconAlertTriangle,
  IconTarget,
  IconHelpHexagon,
  IconArrowRight,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import type { GraphNode } from "@/lib/ui/use-project-data";
import { alertSignFor, paletteFor } from "./knowledge-graph-style";

/** Where each display group is anchored around the centered node. */
const REGION_STYLE: Record<string, React.CSSProperties> = {
  "Supporting & Governing Documents": { left: 0, top: "2%" },
  "Governing Policies / SOPs": { left: "50%", top: 0, transform: "translateX(-50%)" },
  "KPIs & Metrics": { right: 0, top: "2%" },
  Queries: { right: 0, top: "42%" },
  Dashboards: { right: 0, bottom: "2%" },
  "Linked Data Sources": { left: "50%", bottom: 0, transform: "translateX(-50%)" },
  "Related Entities": { left: 0, top: "42%" },
  "Related Processes": { left: 0, bottom: "2%" },
  "Insights / Findings": { left: "30%", bottom: "20%" },
  Recommendations: { left: "55%", bottom: "20%" },
  Project: { left: "50%", top: "2%", transform: "translateX(-50%)" },
};

const REGION_ORDER = [
  "Supporting & Governing Documents",
  "Governing Policies / SOPs",
  "KPIs & Metrics",
  "Queries",
  "Dashboards",
  "Linked Data Sources",
  "Related Entities",
  "Related Processes",
  "Insights / Findings",
  "Recommendations",
  "Project",
];

interface Point {
  x: number;
  y: number;
}

interface Layout {
  width: number;
  height: number;
  center: Point | null;
  byId: Record<number, Point>;
}

interface CanvasEdge {
  id: number;
  source: number;
  target: number;
  confidence: number;
  type?: string;
}

interface CanvasProps {
  centerNode: GraphNode;
  nodes: GraphNode[];
  edges: CanvasEdge[];
  selectedNodeKey: string | null;
  tracedNodeIds: Set<number> | null;
  onNodeClick: (node: GraphNode) => void;
}

/** Max nodes rendered per display group so clusters stay readable. */
const MAX_PER_GROUP = 6;

/** Pull a line endpoint back toward the other end so the arrow clears the node. */
function trim(
  from: Point,
  to: Point,
  pad: number,
): Point {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.hypot(dx, dy) || 1;
  return { x: to.x - (dx / len) * pad, y: to.y - (dy / len) * pad };
}

function humanizeRel(type: string | undefined): string {
  if (!type) return "";
  return type.replace(/[_-]+/g, " ").trim();
}

function AlertSign({ type }: { type: string }) {
  const sign = alertSignFor(type);
  if (!sign) return null;
  const common = "absolute -right-1.5 -top-1.5 rounded-full p-0.5 shadow-sm";
  if (sign === "risk")
    return (
      <span className={cn(common, "bg-danger text-white")}>
        <IconAlertTriangle size={11} />
      </span>
    );
  if (sign === "warning")
    return (
      <span className={cn(common, "bg-warning text-white")}>
        <IconAlertTriangle size={11} />
      </span>
    );
  if (sign === "opportunity")
    return (
      <span className={cn(common, "bg-success text-white")}>
        <IconTarget size={11} />
      </span>
    );
  if (sign === "gap")
    return (
      <span className={cn(common, "bg-[#7C3AED] text-white")}>
        <IconHelpHexagon size={11} />
      </span>
    );
  return (
    <span className={cn(common, "bg-[#EA580C] text-white")}>
      <IconArrowRight size={11} />
    </span>
  );
}

function NodeChip({
  node,
  selected,
  dimmed,
  onClick,
  nodeRef,
}: {
  node: GraphNode;
  selected: boolean;
  dimmed: boolean;
  onClick: () => void;
  nodeRef: (el: HTMLButtonElement | null) => void;
}) {
  const palette = paletteFor(node.type);
  const conf = node.confidence;
  return (
    <button
      ref={nodeRef}
      type="button"
      onClick={onClick}
      title={node.summary || node.label}
      className={cn(
        "relative flex w-[200px] max-w-full items-center gap-2 rounded-lg border bg-white px-2.5 py-2 text-left shadow-sm transition-all hover:shadow-md",
        selected && "ring-2 ring-offset-1",
        dimmed && "opacity-25",
      )}
      style={{
        borderColor: palette.border,
        ...(selected ? { boxShadow: `0 0 0 2px ${palette.border}` } : {}),
      }}
    >
      <span
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: palette.dot }}
      />
      <span
        className="min-w-0 flex-1 truncate text-[12px] font-medium"
        style={{ color: palette.text }}
      >
        {node.label}
      </span>
      {typeof conf === "number" && conf > 0 && (
        <span className="shrink-0 rounded bg-slate-100 px-1 py-0.5 text-[10px] font-semibold text-slate-500">
          {conf.toFixed(2)}
        </span>
      )}
      <AlertSign type={node.type} />
    </button>
  );
}

export function KnowledgeGraphCanvas({
  centerNode,
  nodes,
  edges,
  selectedNodeKey,
  tracedNodeIds,
  onNodeClick,
}: CanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const centerRef = useRef<HTMLButtonElement | null>(null);
  const nodeEls = useRef<Map<number, HTMLButtonElement>>(new Map());
  const [layout, setLayout] = useState<Layout>({
    width: 0,
    height: 0,
    center: null,
    byId: {},
  });

  const others = nodes.filter((n) => n.id !== centerNode.id);
  const byGroup = new Map<string, GraphNode[]>();
  for (const n of others) {
    const g = n.displayGroup ?? "Related Entities";
    const arr = byGroup.get(g) ?? [];
    arr.push(n);
    byGroup.set(g, arr);
  }

  const measure = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const base = container.getBoundingClientRect();
    const centerEl = centerRef.current;
    const center: Point | null = centerEl
      ? (() => {
          const r = centerEl.getBoundingClientRect();
          return {
            x: r.left - base.left + r.width / 2,
            y: r.top - base.top + r.height / 2,
          };
        })()
      : null;
    const byId: Record<number, Point> = {};
    nodeEls.current.forEach((el, id) => {
      const r = el.getBoundingClientRect();
      byId[id] = {
        x: r.left - base.left + r.width / 2,
        y: r.top - base.top + r.height / 2,
      };
    });
    setLayout({
      width: container.scrollWidth,
      height: container.scrollHeight,
      center,
      byId,
    });
  }, []);

  useLayoutEffect(() => {
    measure();
  }, [measure, nodes, centerNode.id]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(container);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [measure]);

  const centerPalette = paletteFor(centerNode.type, true);
  const isDimmed = (id: number) =>
    tracedNodeIds !== null && !tracedNodeIds.has(id);

  return (
    <div
      ref={containerRef}
      className="relative min-h-[720px] w-full overflow-auto rounded-lg border border-line-tertiary bg-[radial-gradient(circle,#eef2f7_1px,transparent_1px)] [background-size:22px_22px]"
    >
      {/* Connector overlay (behind node cards): directional arrows from each
          related source toward / away from the center, per the edge direction. */}
      <svg
        className="pointer-events-none absolute left-0 top-0"
        width={layout.width || "100%"}
        height={layout.height || "100%"}
      >
        <defs>
          <marker
            id="kg-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
          </marker>
          <marker
            id="kg-arrow-dim"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#e2e8f0" />
          </marker>
        </defs>
        {layout.center &&
          edges.map((e) => {
            const isCenterEdge =
              e.source === centerNode.id || e.target === centerNode.id;
            if (!isCenterEdge || !layout.center) return null;
            const srcPt =
              e.source === centerNode.id ? layout.center : layout.byId[e.source];
            const tgtPt =
              e.target === centerNode.id ? layout.center : layout.byId[e.target];
            if (!srcPt || !tgtPt) return null;
            // Trim endpoints so the arrowhead clears the center circle / node chip.
            const p1 = trim(tgtPt, srcPt, e.source === centerNode.id ? 64 : 16);
            const p2 = trim(srcPt, tgtPt, e.target === centerNode.id ? 64 : 16);
            const traced =
              tracedNodeIds === null ||
              (tracedNodeIds.has(e.source) && tracedNodeIds.has(e.target));
            return (
              <line
                key={e.id}
                x1={p1.x}
                y1={p1.y}
                x2={p2.x}
                y2={p2.y}
                stroke={traced ? "#94a3b8" : "#e2e8f0"}
                strokeWidth={traced ? 1.5 : 1}
                strokeDasharray={traced ? undefined : "4 4"}
                markerEnd={`url(#${traced ? "kg-arrow" : "kg-arrow-dim"})`}
              />
            );
          })}
      </svg>

      {/* Edge relationship labels + confidence (above the connectors) */}
      {layout.center &&
        edges.map((e) => {
          const isCenterEdge =
            e.source === centerNode.id || e.target === centerNode.id;
          if (!isCenterEdge || !layout.center) return null;
          const srcPt =
            e.source === centerNode.id ? layout.center : layout.byId[e.source];
          const tgtPt =
            e.target === centerNode.id ? layout.center : layout.byId[e.target];
          if (!srcPt || !tgtPt) return null;
          const label = humanizeRel(e.type);
          if (!label && !e.confidence) return null;
          const traced =
            tracedNodeIds === null ||
            (tracedNodeIds.has(e.source) && tracedNodeIds.has(e.target));
          const mx = (srcPt.x + tgtPt.x) / 2;
          const my = (srcPt.y + tgtPt.y) / 2;
          return (
            <div
              key={`lbl-${e.id}`}
              className={cn(
                "pointer-events-none absolute z-[6] flex -translate-x-1/2 -translate-y-1/2 items-center gap-1 whitespace-nowrap rounded border border-line-tertiary bg-white px-1.5 py-0.5 text-[9px] font-medium shadow-sm",
                traced ? "text-ink-tertiary" : "text-line-secondary opacity-60",
              )}
              style={{ left: mx, top: my }}
            >
              {label && <span>{label}</span>}
              {typeof e.confidence === "number" && e.confidence > 0 && (
                <span className="rounded bg-slate-100 px-1 font-semibold text-slate-500">
                  {e.confidence.toFixed(2)}
                </span>
              )}
            </div>
          );
        })}

      {/* Center node */}
      <button
        ref={centerRef}
        type="button"
        onClick={() => onNodeClick(centerNode)}
        className="absolute left-1/2 top-1/2 z-10 flex h-[120px] w-[120px] -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full border-2 px-3 text-center shadow-lg"
        style={{ backgroundColor: centerPalette.bg, borderColor: centerPalette.border }}
      >
        <span className="line-clamp-3 text-[13px] font-semibold text-white">
          {centerNode.label}
        </span>
        {typeof centerNode.confidence === "number" && centerNode.confidence > 0 && (
          <span className="mt-1 rounded bg-white/15 px-1.5 py-0.5 text-[10px] font-semibold text-white">
            {centerNode.confidence.toFixed(2)}
          </span>
        )}
      </button>

      {/* Display-group clusters */}
      {REGION_ORDER.filter((g) => byGroup.has(g)).map((group) => {
        const groupNodes = byGroup.get(group) ?? [];
        const style = REGION_STYLE[group] ?? REGION_STYLE["Related Entities"];
        return (
          <div
            key={group}
            className="absolute z-[5] flex max-w-[230px] flex-col gap-1.5"
            style={style}
          >
            <div className="text-[10px] font-semibold uppercase tracking-wide text-ink-tertiary">
              {group}
            </div>
            {groupNodes.slice(0, MAX_PER_GROUP).map((n) => (
              <NodeChip
                key={n.id}
                node={n}
                selected={selectedNodeKey === n.graphKey}
                dimmed={isDimmed(n.id)}
                onClick={() => onNodeClick(n)}
                nodeRef={(el) => {
                  if (el) nodeEls.current.set(n.id, el);
                  else nodeEls.current.delete(n.id);
                }}
              />
            ))}
            {groupNodes.length > MAX_PER_GROUP && (
              <span className="pl-1 text-[10px] font-medium text-ink-tertiary">
                +{groupNodes.length - MAX_PER_GROUP} more
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
