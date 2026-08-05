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


/** Icon for the center circle, chosen by node type. */
export function centerIconFor(type: string): Icon {
  if (type === "project") return IconTopologyStar3;
  if (type === "process") return IconSettings;
  if (type === "kpi" || type === "metric" || type === "threshold" || type === "benchmark")
    return IconChartLine;
  if (type === "dashboard") return IconChartBar;
  if (type === "data_source" || type === "datasource" || type === "table")
    return IconDatabase;
  if (type === "query" || type === "saved_query") return IconTable;
  if (
    type === "risk" || type === "warning" || type === "gap" ||
    type === "process_gap" || type === "data_gap" || type === "compliance_gap" ||
    type === "audit_finding" || type === "insight"
  )
    return IconAlertTriangle;
  return IconFileText;
}