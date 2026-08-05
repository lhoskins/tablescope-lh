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
import { alertSignFor, paletteFor } from "../knowledge-graph-style";import { CanvasEdge } from "./canvas-edge";



/** Dash pattern for an edge connector by its style. */
export function edgeDash(style: CanvasEdge["connectorStyle"]): string | undefined {
  if (style === "dotted") return "4 4";
  if (style === "dashed") return "8 6";
  return undefined;
}