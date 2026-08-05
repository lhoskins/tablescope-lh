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
import { alertSignFor, paletteFor } from "../knowledge-graph-style";


/** Human-friendly node-type subtitle for the center circle. */
export function humanizeType(type: string | undefined): string {
  if (!type) return "";
  return type.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).trim();
}