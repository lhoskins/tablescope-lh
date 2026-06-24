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
import { alertSignFor, paletteFor } from "./knowledge-graph-style";

/** Order display groups radiate around the center node. */
const REGION_ORDER = [
  "Supporting & Governing Documents",
  "Authoritative Reference Library",
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

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface CanvasEdge {
  id: GraphId;
  source: GraphId;
  target: GraphId;
  confidence: number;
  type?: string;
}

interface CanvasProps {
  centerNode: GraphNode;
  nodes: GraphNode[];
  edges: CanvasEdge[];
  selectedNodeKey: string | null;
  tracedNodeIds: Set<GraphId> | null;
  onNodeClick: (node: GraphNode) => void;
}

// ── Layout constants (px) ────────────────────────────────────────────
const MAX_PER_GROUP = 6;
const PILL_W = 210;
const PILL_H = 38;
const PILL_GAP = 8;
const GROUP_LABEL_H = 22;
const GROUP_GAP = 26;
const OVERFLOW_H = 16;
const CENTER_R = 60;
const CENTER_GAP = 320; // horizontal space reserved for the center circle + labels
const PAD = 28;
const COL_W = PILL_W;
// Pull edge endpoints slightly off the pill/circle border so arrowheads sit in
// the gap and never overlap pill text or run through the center circle.
const ARROW_INSET = 8;
const CENTER_ARROW_INSET = 6;

function humanizeRel(type: string | undefined): string {
  if (!type) return "";
  return type.replace(/[_-]+/g, " ").trim();
}

/** Border point of a rectangle on the ray from its center toward `toward`. */
function rectBorderPoint(rect: Rect, toward: Point): Point {
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h / 2;
  const dx = toward.x - cx;
  const dy = toward.y - cy;
  if (dx === 0 && dy === 0) return { x: cx, y: cy };
  const tx = dx !== 0 ? rect.w / 2 / Math.abs(dx) : Infinity;
  const ty = dy !== 0 ? rect.h / 2 / Math.abs(dy) : Infinity;
  const t = Math.min(tx, ty);
  return { x: cx + dx * t, y: cy + dy * t };
}

/** Point on a circle's edge on the ray toward `toward`. */
function circleBorderPoint(c: Point, toward: Point, r: number): Point {
  const dx = toward.x - c.x;
  const dy = toward.y - c.y;
  const len = Math.hypot(dx, dy) || 1;
  return { x: c.x + (dx / len) * r, y: c.y + (dy / len) * r };
}

/** Move `from` toward `to` by `amount` px (used to inset edge endpoints). */
export function insetPoint(from: Point, to: Point, amount: number): Point {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.hypot(dx, dy) || 1;
  return { x: from.x + (dx / len) * amount, y: from.y + (dy / len) * amount };
}

/** Smooth cubic edge that bows horizontally away from the center column. */
export function edgePath(p1: Point, p2: Point): string {
  const dx = p2.x - p1.x;
  const c1 = { x: p1.x + dx * 0.35, y: p1.y };
  const c2 = { x: p2.x - dx * 0.35, y: p2.y };
  return `M ${p1.x} ${p1.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${p2.x} ${p2.y}`;
}

/** Point on the cubic edge at t=0.5 — where the relationship label sits. */
function edgeMidpoint(p1: Point, p2: Point): Point {
  const dx = p2.x - p1.x;
  const c1 = { x: p1.x + dx * 0.35, y: p1.y };
  const c2 = { x: p2.x - dx * 0.35, y: p2.y };
  return {
    x: 0.125 * p1.x + 0.375 * c1.x + 0.375 * c2.x + 0.125 * p2.x,
    y: 0.125 * p1.y + 0.375 * c1.y + 0.375 * c2.y + 0.125 * p2.y,
  };
}

/** Icon for the center circle, chosen by node type. */
function centerIconFor(type: string): Icon {
  if (type === "project") return IconTopologyStar3;
  if (type === "process") return IconSettings;
  if (type === "kpi" || type === "metric" || type === "threshold" || type === "benchmark")
    return IconChartLine;
  if (type === "dashboard") return IconChartBar;
  if (type === "data_source" || type === "datasource" || type === "table")
    return IconDatabase;
  if (type === "query" || type === "saved_query") return IconTable;
  if (
    type === "risk" || type === "warning" || type === "gap" ||
    type === "process_gap" || type === "data_gap" || type === "compliance_gap" ||
    type === "audit_finding" || type === "insight"
  )
    return IconAlertTriangle;
  return IconFileText;
}

function groupHeight(count: number): number {
  const shown = Math.min(count, MAX_PER_GROUP);
  const overflow = count > MAX_PER_GROUP ? OVERFLOW_H : 0;
  return GROUP_LABEL_H + shown * PILL_H + (shown - 1) * PILL_GAP + overflow;
}

interface GroupBox {
  group: string;
  nodes: GraphNode[];
  x: number;
  y: number;
  side: "left" | "right";
}

interface ComputedLayout {
  width: number;
  height: number;
  center: Point;
  rects: Map<string, Rect>;
  groups: GroupBox[];
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
  style,
}: {
  node: GraphNode;
  selected: boolean;
  dimmed: boolean;
  onClick: () => void;
  style: React.CSSProperties;
}) {
  const palette = paletteFor(node.type);
  const conf = node.confidence;
  return (
    <button
      type="button"
      onClick={onClick}
      title={node.summary || node.label}
      className={cn(
        "absolute z-[5] flex items-center gap-2 rounded-lg border bg-white px-2.5 text-left shadow-sm transition-all hover:shadow-md",
        selected && "ring-2 ring-offset-1",
        dimmed && "opacity-25",
      )}
      style={{
        ...style,
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

/** Deterministic two-column radial layout: groups stack down each side of the
 *  center with fixed sizing, so pills never overlap and the canvas height grows
 *  with the content (responsive). */
function computeLayout(centerId: GraphId, nodes: GraphNode[]): ComputedLayout {
  const byGroup = new Map<string, GraphNode[]>();
  for (const n of nodes) {
    if (n.id === centerId) continue;
    const g = n.displayGroup ?? "Related Entities";
    const arr = byGroup.get(g) ?? [];
    arr.push(n);
    byGroup.set(g, arr);
  }
  const present = REGION_ORDER.filter((g) => byGroup.has(g));

  // Greedy balance: assign each group to the currently-shorter column.
  let leftH = PAD;
  let rightH = PAD;
  const leftGroups: { group: string; nodes: GraphNode[]; h: number }[] = [];
  const rightGroups: { group: string; nodes: GraphNode[]; h: number }[] = [];
  for (const group of present) {
    const groupNodes = byGroup.get(group) ?? [];
    const h = groupHeight(groupNodes.length);
    if (leftH <= rightH) {
      leftGroups.push({ group, nodes: groupNodes, h });
      leftH += h + GROUP_GAP;
    } else {
      rightGroups.push({ group, nodes: groupNodes, h });
      rightH += h + GROUP_GAP;
    }
  }

  const leftX = PAD;
  const rightX = PAD + COL_W + CENTER_GAP;
  const width = rightX + COL_W + PAD;
  const contentH = Math.max(leftH, rightH, PAD + CENTER_R * 2);
  const height = contentH + PAD;
  const center: Point = { x: PAD + COL_W + CENTER_GAP / 2, y: height / 2 };

  const rects = new Map<string, Rect>();
  const groups: GroupBox[] = [];

  const place = (
    col: { group: string; nodes: GraphNode[]; h: number }[],
    x: number,
    side: "left" | "right",
    colHeight: number,
  ) => {
    // Vertically center the column block within the canvas.
    let y = (height - (colHeight - PAD - GROUP_GAP)) / 2;
    if (y < PAD) y = PAD;
    for (const g of col) {
      groups.push({ group: g.group, nodes: g.nodes, x, y, side });
      let py = y + GROUP_LABEL_H;
      for (const n of g.nodes.slice(0, MAX_PER_GROUP)) {
        rects.set(String(n.id), { x, y: py, w: PILL_W, h: PILL_H });
        py += PILL_H + PILL_GAP;
      }
      y += g.h + GROUP_GAP;
    }
  };

  place(leftGroups, leftX, "left", leftH);
  place(rightGroups, rightX, "right", rightH);

  return { width, height, center, rects, groups };
}

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
    return rectBorderPoint(rect, toward);
  };

  const centerOf = (id: GraphId): Point | null => {
    if (id === centerNode.id) return layout.center;
    const r = layout.rects.get(String(id));
    return r ? { x: r.x + r.w / 2, y: r.y + r.h / 2 } : null;
  };

  const tracingActive = tracedNodeIds !== null;

  // Pre-compute drawable edges (both endpoints positioned + inset).
  const drawn = edges
    .map((e) => {
      const sc = centerOf(e.source);
      const tc = centerOf(e.target);
      if (!sc || !tc) return null;
      const rawP1 = attach(e.source, tc);
      const rawP2 = attach(e.target, sc);
      if (!rawP1 || !rawP2) return null;
      const inset1 = e.source === centerNode.id ? CENTER_ARROW_INSET : ARROW_INSET;
      const inset2 = e.target === centerNode.id ? CENTER_ARROW_INSET : ARROW_INSET;
      const p1 = insetPoint(rawP1, rawP2, inset1);
      const p2 = insetPoint(rawP2, rawP1, inset2);
      const traced =
        tracedNodeIds === null ||
        (tracedNodeIds.has(e.source) && tracedNodeIds.has(e.target));
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
              refX="6"
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
              refX="6"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#e2e8f0" />
            </marker>
          </defs>
          {drawn.map(({ e, p1, p2, traced }) => (
            <path
              key={String(e.id)}
              d={edgePath(p1, p2)}
              fill="none"
              stroke={traced ? "#94a3b8" : "#e2e8f0"}
              strokeWidth={traced ? 1.5 : 1}
              strokeDasharray={traced ? undefined : "4 4"}
              markerEnd={`url(#${traced ? "kg-arrow" : "kg-arrow-dim"})`}
            />
          ))}
        </svg>

        {/* Edge relationship labels + confidence at the curve midpoint.
            Hidden for low-confidence non-center edges to cut clutter. */}
        {drawn.map(({ e, p1, p2, traced, showLabel }) => {
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
          className="absolute z-10 flex flex-col items-center justify-center rounded-full px-3 text-center text-white shadow-[0_12px_28px_rgba(15,23,42,0.28)]"
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
          <span className="line-clamp-2 text-[12px] font-semibold leading-tight text-white">
            {centerNode.label}
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
