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


export function AlertSign({ type }: { type: string }) {
  const sign = alertSignFor(type);
  if (!sign) return null;
  const common = "absolute -right-1.5 -top-1.5 rounded-full p-0.5 shadow-sm";
  if (sign === "risk")
    return (
      <span className={cn(common, "bg-danger text-white")}>
        <IconAlertTriangle size={11} />
      </span>
    );
  if (sign === "warning")
    return (
      <span className={cn(common, "bg-warning text-white")}>
        <IconAlertTriangle size={11} />
      </span>
    );
  if (sign === "opportunity")
    return (
      <span className={cn(common, "bg-success text-white")}>
        <IconTarget size={11} />
      </span>
    );
  if (sign === "gap")
    return (
      <span className={cn(common, "bg-[#7C3AED] text-white")}>
        <IconHelpHexagon size={11} />
      </span>
    );
  return (
    <span className={cn(common, "bg-[#EA580C] text-white")}>
      <IconArrowRight size={11} />
    </span>
  );
}