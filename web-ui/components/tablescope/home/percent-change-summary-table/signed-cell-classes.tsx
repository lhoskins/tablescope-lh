"use client";


import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { formatPercentChange } from "@/lib/insights/time-series";
import { insightAnchorId } from "@/lib/insights/return-target";
import type {
  PercentChangeSummaryCell,
  PercentChangeSummaryPeriod,
  PercentChangeSummaryRow,
  PercentChangeSummarySort,
  PercentChangeSummaryStatistics,
} from "@/lib/api/home-intelligence";
import {
  IconArrowUp,
  IconArrowDown,
  IconInfoCircle,
} from "@tabler/icons-react";import { ZERO_TOLERANCE } from "./zero-tolerance";



export function signedCellClasses(
  ratio: number | null | undefined,
  presentation: "default" | "executive" = "default",
): string {
  // The figure carries the colour; the cell stays on the table's own
  // background. Filling every cell (this once painted #74C990/#EA7975/#626365
  // edge to edge) turned the grid into a heat map where the numbers were the
  // least legible thing in it, and read as a different application to the rest
  // of Tablescope. Sign is still immediately scannable from the text colour,
  // and a reader can now follow a row without fighting the fills.
  const blank = ratio === null || ratio === undefined;
  if (blank) {
    // Executive Business Insight presentation treats a blank (no comparable
    // prior period) the same as a literal 0.0% change -- shown and colored
    // identically -- rather than a dash. Project Insights (default) keeps
    // the original "no data" treatment.
    if (presentation === "executive") return "text-ink-tertiary";
    return "text-ink-tertiary";
  }
  const zero = Math.abs(ratio) <= ZERO_TOLERANCE;
  if (presentation === "executive") {
    // A flat period is information, not an alert: keep it quiet so the eye
    // goes to the periods that actually moved.
    if (zero) return "text-ink-tertiary";
    // The `-strong` tokens, not the tinted-chip ones: printed on white at
    // 12px, `--color-success`/`--color-danger` are close enough in luminance
    // that a row of them reads as uniformly dark rather than as movement in
    // two directions.
    return ratio > 0
      ? "text-success-strong font-semibold"
      : "text-danger-strong font-semibold";
  }
  // Default (Project Insights) keeps its subtle tint -- only the executive
  // briefing's full-bleed fills were the problem.
  if (zero) return "text-ink-secondary";
  return ratio > 0 ? "bg-success-bg text-success" : "bg-danger-bg text-danger";
}
