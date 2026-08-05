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
import { alertSignFor, paletteFor } from "../knowledge-graph-style";import { EdgeStrength } from "./edge-strength";
import { CanvasEdge } from "./canvas-edge";
import { edgeDash } from "./edge-dash";
import { edgeOpacity } from "./edge-opacity";



/** Stroke appearance for a relationship connector by its evidence class. */
export function connectorStroke(
  style: CanvasEdge["connectorStyle"],
  strength: EdgeStrength | undefined,
  traced: boolean,
): { stroke: string; strokeWidth: number; dash?: string; marker: string; opacity: number } {
  if (traced) {
    return { stroke: "#94a3b8", strokeWidth: 1.5, marker: "kg-arrow", opacity: 1 };
  }
  const opacity = edgeOpacity(strength);
  const dash = edgeDash(style);
  switch (style) {
    case "solid":
      // Explicit project evidence — a confident solid line.
      return { stroke: "#94a3b8", strokeWidth: 1.25, marker: "kg-arrow", opacity };
    case "dashed":
      // Best-practice recommendation — faint amber dashes.
      return { stroke: "#fbbf24", strokeWidth: 1, dash, marker: "kg-arrow-rec", opacity };
    case "dotted":
    default:
      // Inferred / weak relationship — light dotted line.
      return { stroke: "#cbd5e1", strokeWidth: 1, dash, marker: "kg-arrow-dim", opacity };
  }
}