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



export interface CanvasEdge {
  id: GraphId;
  source: GraphId;
  target: GraphId;
  confidence: number;
  type?: string;
  connectorStyle?: "solid" | "dotted" | "dashed" | "hidden";
  relationshipStrength?: EdgeStrength;
}