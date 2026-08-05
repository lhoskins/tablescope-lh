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


/** Order display groups radiate around the center node. */
export const REGION_ORDER = [
  "Supporting & Governing Documents",
  "Authoritative Reference Library",
  "Governing Policies / SOPs",
  "KPIs & Metrics",
  "Queries",
  "Dashboards",
  "Linked Data Sources",
  "Related Entities",
  "Related Processes",
  "Insights / Findings",
  "Recommendations",
  "Project",
];