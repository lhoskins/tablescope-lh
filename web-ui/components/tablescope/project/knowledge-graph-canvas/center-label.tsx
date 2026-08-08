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


/** Shorten a long center label with a middle ellipsis (keeps head + tail). */
export function centerLabel(label: string): string {
  if (!label) return "";
  const clean = label.replace(/\.(docx|pdf|pptx|xlsx|csv|txt)$/i, "");
  if (clean.length <= 34) return clean;
  return `${clean.slice(0, 16)}\u2026${clean.slice(-14)}`;
}