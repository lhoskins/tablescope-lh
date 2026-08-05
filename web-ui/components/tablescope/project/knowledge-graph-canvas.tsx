"use client";


import React, { useMemo } from "react";
import {
  IconAlertTriangle,
  IconArrowRight,
  IconChartBar,
  IconChartLine,
  IconDatabase,
  IconFileText,
  IconHelpHexagon,
  IconSettings,
  IconTable,
  IconTarget,
  IconTopologyStar3,
  type Icon,
} from "@tabler/icons-react";
import type { GraphId, GraphNode } from "@/lib/ui/use-project-data";
import { cn } from "@/lib/cn";
import { alertSignFor, paletteFor } from "./knowledge-graph-style";import { Point } from "./knowledge-graph-canvas/point";
import { connectorStroke } from "./knowledge-graph-canvas/connector-stroke";
import { CanvasProps } from "./knowledge-graph-canvas/canvas-props";
import { MAX_PER_GROUP } from "./knowledge-graph-canvas/max-per-group";
import { PILL_W } from "./knowledge-graph-canvas/pill-w";
import { PILL_H } from "./knowledge-graph-canvas/pill-h";
import { CENTER_R } from "./knowledge-graph-canvas/center-r";
import { MARKER_TOUCH_OFFSET } from "./knowledge-graph-canvas/marker-touch-offset";
import { SHOW_EDGE_LABELS } from "./knowledge-graph-canvas/show-edge-labels";
import { centerLabel } from "./knowledge-graph-canvas/center-label";
import { humanizeType } from "./knowledge-graph-canvas/humanize-type";
import { humanizeRel } from "./knowledge-graph-canvas/humanize-rel";
import { rectSidePoint } from "./knowledge-graph-canvas/rect-side-point";
import { circleBorderPoint } from "./knowledge-graph-canvas/circle-border-point";
import { moveToward } from "./knowledge-graph-canvas/move-toward";
import { edgePath } from "./knowledge-graph-canvas/edge-path";
import { edgeMidpoint } from "./knowledge-graph-canvas/edge-midpoint";
import { centerIconFor } from "./knowledge-graph-canvas/center-icon-for";
import { NodeChip } from "./knowledge-graph-canvas/node-chip";
import { computeLayout } from "./knowledge-graph-canvas/compute-layout";



export function KnowledgeGraphCanvas({
  centerNode,
  nodes,
  edges,
  selectedNodeKey,
  tracedNodeIds,
  onNodeClick,
}: CanvasProps) {
  const layout = useMemo(
    () => computeLayout(centerNode.id, nodes),
    [centerNode.id, nodes],
  );

  const centerPalette = paletteFor(centerNode.type, true);
  const isDimmed = (id: GraphId) =>
    tracedNodeIds !== null && !tracedNodeIds.has(id);

  /** Resolve the geometric attach point of an endpoint toward the other end. */
  const attach = (id: GraphId, toward: Point): Point | null => {
    if (id === centerNode.id) {
      return circleBorderPoint(layout.center, toward, CENTER_R + 4);
    }
    const rect = layout.rects.get(String(id));
    if (!rect) return null;
    return rectSidePoint(rect, toward);
  };

  const centerOf = (id: GraphId): Point | null => {
    if (id === centerNode.id) return layout.center;
    const r = layout.rects.get(String(id));
    return r ? { x: r.x + r.w / 2, y: r.y + r.h / 2 } : null;
  };

  const tracingActive = tracedNodeIds !== null;

  // Pre-compute drawable edges. The start point sits just off the source
  // boundary; the end point is nudged slightly inside the target so the
  // arrowhead visually touches the pill/circle edge (no gap, no overshoot).
  const drawn = edges
    .map((e) => {
      const sc = centerOf(e.source);
      const tc = centerOf(e.target);
      if (!sc || !tc) return null;
      const rawP1 = attach(e.source, tc);
      const rawP2 = attach(e.target, sc);
      if (!rawP1 || !rawP2) return null;
      const p1 = moveToward(rawP1, tc, 1);
      const p2 = moveToward(rawP2, tc, MARKER_TOUCH_OFFSET);
      // "traced" means this edge is part of an *active* trace-to-evidence
      // highlight, not merely that no trace filter is set. Treating "no
      // trace active" as "every edge is traced" (the previous behavior)
      // made connectorStroke() always take its flat solid-gray branch,
      // silently ignoring connectorStyle/relationshipStrength for the
      // default (non-tracing) view — the dotted/dashed relationship-evidence
      // styling never rendered unless a trace was actively selected.
      const traced =
        tracingActive &&
        tracedNodeIds!.has(e.source) &&
        tracedNodeIds!.has(e.target);
      const isCenterEdge =
        e.source === centerNode.id || e.target === centerNode.id;
      // Reduce clutter: in the default view only label center-connected or
      // high-confidence edges; while tracing only label the traced path.
      const showLabel = tracingActive
        ? traced
        : isCenterEdge || e.confidence >= 0.9;
      return { e, p1, p2, traced, showLabel };
    })
    .filter((v): v is NonNullable<typeof v> => v !== null);

  return (
    <div
      className="relative h-full w-full overflow-auto rounded-lg border border-line-tertiary bg-[radial-gradient(circle,#eef2f7_1px,transparent_1px)] [background-size:22px_22px]"
    >
      <div
        className="relative"
        style={{ width: layout.width, height: layout.height, minWidth: "100%" }}
      >
        {/* Connector overlay: directional arrows from the center toward each
            related source (and source-to-source lineage), attached to the pill
            edge nearest the other endpoint. */}
        <svg
          className="pointer-events-none absolute left-0 top-0"
          width={layout.width}
          height={layout.height}
        >
          <defs>
            <marker
              id="kg-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
            </marker>
            <marker
              id="kg-arrow-dim"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#cbd5e1" />
            </marker>
            <marker
              id="kg-arrow-rec"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#fbbf24" />
            </marker>
          </defs>
          {drawn.map(({ e, p1, p2, traced }) => {
            const s = connectorStroke(e.connectorStyle, e.relationshipStrength, traced);
            return (
              <path
                key={String(e.id)}
                d={edgePath(p1, p2)}
                fill="none"
                stroke={s.stroke}
                strokeWidth={s.strokeWidth}
                strokeDasharray={s.dash}
                strokeOpacity={s.opacity}
                markerEnd={`url(#${s.marker})`}
              />
            );
          })}
        </svg>

        {/* Edge relationship labels are disabled by default (too cluttered);
            relationship details live in the right panel / trace-to-evidence. */}
        {SHOW_EDGE_LABELS && drawn.map(({ e, p1, p2, traced, showLabel }) => {
          if (!showLabel) return null;
          const label = humanizeRel(e.type);
          if (!label && !e.confidence) return null;
          const mid = edgeMidpoint(p1, p2);
          const mx = mid.x;
          const my = mid.y;
          return (
            <div
              key={`lbl-${String(e.id)}`}
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

        {/* Center node — dark-blue fill with two white border rings + glow */}
        <button
          type="button"
          data-testid="kg-center-node"
          onClick={() => onNodeClick(centerNode)}
          title={centerNode.label}
          className="absolute z-10 flex flex-col items-center justify-center rounded-full px-2 text-center text-white shadow-[0_12px_28px_rgba(15,23,42,0.28)]"
          style={{
            left: layout.center.x - CENTER_R,
            top: layout.center.y - CENTER_R,
            width: CENTER_R * 2,
            height: CENTER_R * 2,
            background:
              "radial-gradient(circle at 35% 28%, #1E5BB8 0%, #0B3B82 42%, #062A63 100%)",
            border: "3px solid #FFFFFF",
            boxShadow:
              "0 0 0 4px rgba(255,255,255,0.9), 0 0 0 7px rgba(30,91,184,0.22), 0 14px 32px rgba(6,42,99,0.35)",
          }}
        >
          <span className="pointer-events-none absolute inset-[7px] rounded-full border border-white/80" />
          {(() => {
            const Icon = centerIconFor(centerNode.type);
            return (
              <span className="mb-1 flex h-7 w-7 items-center justify-center rounded-full border border-white/50 bg-white/10">
                <Icon size={17} />
              </span>
            );
          })()}
          <span className="line-clamp-3 max-w-[100px] break-words text-[12px] font-semibold leading-tight text-white">
            {centerLabel(centerNode.label)}
          </span>
          <span className="mt-0.5 text-[10px] text-white/75">
            {humanizeType(centerNode.type)}
          </span>
          {typeof centerNode.confidence === "number" &&
            centerNode.confidence > 0 && (
              <span className="mt-1 rounded bg-white/15 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                {centerNode.confidence.toFixed(2)}
              </span>
            )}
        </button>

        {/* Display-group labels */}
        {layout.groups.map((g) => (
          <div
            key={g.group}
            className={cn(
              "absolute z-[5] text-[10px] font-semibold uppercase tracking-wide text-ink-tertiary",
              g.side === "left" ? "text-left" : "text-left",
            )}
            style={{ left: g.x, top: g.y, width: PILL_W }}
          >
            {g.group}
          </div>
        ))}

        {/* Pills */}
        {layout.groups.flatMap((g) => {
          const items = g.nodes.slice(0, MAX_PER_GROUP).map((n) => {
            const rect = layout.rects.get(String(n.id));
            if (!rect) return null;
            return (
              <NodeChip
                key={String(n.id)}
                node={n}
                selected={selectedNodeKey === n.graphKey}
                dimmed={isDimmed(n.id)}
                onClick={() => onNodeClick(n)}
                style={{
                  left: rect.x,
                  top: rect.y,
                  width: rect.w,
                  height: rect.h,
                }}
              />
            );
          });
          const overflow = g.nodes.length - MAX_PER_GROUP;
          if (overflow > 0) {
            const lastRect = layout.rects.get(
              String(g.nodes[MAX_PER_GROUP - 1].id),
            );
            if (lastRect) {
              items.push(
                <span
                  key={`more-${g.group}`}
                  className="absolute z-[5] pl-1 text-[10px] font-medium text-ink-tertiary"
                  style={{ left: g.x, top: lastRect.y + PILL_H + 2 }}
                >
                  +{overflow} more
                </span>,
              );
            }
          }
          return items;
        })}
      </div>
    </div>
  );
}

export { connectorStroke } from "./knowledge-graph-canvas/connector-stroke";
export { rectSidePoint } from "./knowledge-graph-canvas/rect-side-point";
export { insetPoint } from "./knowledge-graph-canvas/inset-point";
export { moveToward } from "./knowledge-graph-canvas/move-toward";
export { edgePath } from "./knowledge-graph-canvas/edge-path";
export { centerLabel } from "./knowledge-graph-canvas/center-label";
