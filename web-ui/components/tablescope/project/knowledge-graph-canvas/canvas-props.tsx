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



export interface CanvasProps {
  centerNode: GraphNode;
  nodes: GraphNode[];
  edges: CanvasEdge[];
  selectedNodeKey: string | null;
  tracedNodeIds: Set<GraphId> | null;
  onNodeClick: (node: GraphNode) => void;
}