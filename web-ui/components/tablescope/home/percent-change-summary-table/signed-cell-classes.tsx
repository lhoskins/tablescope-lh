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
  if (Math.abs(ratio) <= ZERO_TOLERANCE) return "bg-[#626365] text-white";
  if (ratio > 0) return "bg-[#74C990] text-white";
  return "bg-[#EA7975] text-white";
}
