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
import { alertSignFor, paletteFor } from "../knowledge-graph-style";import { Point } from "./point";
import { Rect } from "./rect";



/** Attach point on the pill's vertical edge (left/right side) nearest `toward`.
 *
 * Lines always terminate on the side of the pill facing the other endpoint
 * (the centre circle for a centre→pill edge), at the pill's mid-height — never
 * on the top/bottom edge or in the pill body. */
export function rectSidePoint(rect: Rect, toward: Point): Point {
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h / 2;
  const x = toward.x >= cx ? rect.x + rect.w : rect.x;
  return { x, y: cy };
}