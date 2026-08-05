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
import { alertSignFor, paletteFor } from "../knowledge-graph-style";import { MAX_PER_GROUP } from "./max-per-group";
import { PILL_H } from "./pill-h";
import { PILL_GAP } from "./pill-gap";
import { GROUP_LABEL_H } from "./group-label-h";
import { OVERFLOW_H } from "./overflow-h";



export function groupHeight(count: number): number {
  const shown = Math.min(count, MAX_PER_GROUP);
  const overflow = count > MAX_PER_GROUP ? OVERFLOW_H : 0;
  return GROUP_LABEL_H + shown * PILL_H + (shown - 1) * PILL_GAP + overflow;
}