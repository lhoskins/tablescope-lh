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



/** Smooth cubic edge that bows horizontally away from the center column. */
export function edgePath(p1: Point, p2: Point): string {
  const dx = p2.x - p1.x;
  const c1 = { x: p1.x + dx * 0.35, y: p1.y };
  const c2 = { x: p2.x - dx * 0.35, y: p2.y };
  return `M ${p1.x} ${p1.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${p2.x} ${p2.y}`;
}