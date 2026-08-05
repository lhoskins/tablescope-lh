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



export function signedCellClasses(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "text-ink-tertiary";
  if (Math.abs(ratio) <= ZERO_TOLERANCE) return "text-ink-secondary";
  if (ratio > 0) return "bg-success-bg text-success";
  return "bg-danger-bg text-danger";
}