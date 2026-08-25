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
  if (ratio === null || ratio === undefined) return "text-ink-tertiary";
  const zero = Math.abs(ratio) <= ZERO_TOLERANCE;
  if (presentation === "executive") {
    if (zero) return "bg-[#626365] text-white";
    return ratio > 0 ? "bg-[#74C990] text-white" : "bg-[#EA7975] text-white";
  }
  if (zero) return "text-ink-secondary";
  return ratio > 0 ? "bg-success-bg text-success" : "bg-danger-bg text-danger";
}
