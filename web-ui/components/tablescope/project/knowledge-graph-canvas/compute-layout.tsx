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
import { alertSignFor, paletteFor } from "../knowledge-graph-style";import { REGION_ORDER } from "./region-order";
import { Point } from "./point";
import { Rect } from "./rect";
import { MAX_PER_GROUP } from "./max-per-group";
import { PILL_W } from "./pill-w";
import { PILL_H } from "./pill-h";
import { PILL_GAP } from "./pill-gap";
import { GROUP_LABEL_H } from "./group-label-h";
import { GROUP_GAP } from "./group-gap";
import { CENTER_R } from "./center-r";
import { CENTER_GAP } from "./center-gap";
import { PAD } from "./pad";
import { COL_W } from "./col-w";
import { groupHeight } from "./group-height";
import { GroupBox } from "./group-box";
import { ComputedLayout } from "./computed-layout";



/** Deterministic two-column radial layout: groups stack down each side of the
 *  center with fixed sizing, so pills never overlap and the canvas height grows
 *  with the content (responsive). */
export function computeLayout(centerId: GraphId, nodes: GraphNode[]): ComputedLayout {
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