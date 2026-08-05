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



/** Opacity for an edge connector by its evidence strength. */
export function edgeOpacity(strength: EdgeStrength | undefined): number {
  if (strength === "hidden") return 0.18;
  if (strength === "recommended") return 0.4;
  if (strength === "weak") return 0.25;
  if (strength === "inferred") return 0.7;
  return 1;
}