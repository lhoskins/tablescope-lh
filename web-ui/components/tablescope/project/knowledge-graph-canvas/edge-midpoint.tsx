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



/** Point on the cubic edge at t=0.5 — where the relationship label sits. */
export function edgeMidpoint(p1: Point, p2: Point): Point {
  const dx = p2.x - p1.x;
  const c1 = { x: p1.x + dx * 0.35, y: p1.y };
  const c2 = { x: p2.x - dx * 0.35, y: p2.y };
  return {
    x: 0.125 * p1.x + 0.375 * c1.x + 0.375 * c2.x + 0.125 * p2.x,
    y: 0.125 * p1.y + 0.375 * c1.y + 0.375 * c2.y + 0.125 * p2.y,
  };
}