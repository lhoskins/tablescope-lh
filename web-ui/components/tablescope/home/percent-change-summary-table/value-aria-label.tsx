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



export function valueAriaLabel(
  ratio: number | null | undefined,
  label?: string,
  presentation: "default" | "executive" = "default",
): string {
  if (ratio === null || ratio === undefined) {
    if (presentation === "executive") {
      const description = `No change, ${formatPercentChange(0)}`;
      return label ? `${label}: ${description}` : description;
    }
    return label ? `${label}: No data` : "No data";
  }
  const formatted = formatPercentChange(ratio);
  let description: string;
  if (Math.abs(ratio) <= ZERO_TOLERANCE) {
    description = `No change, ${formatted}`;
  } else if (ratio > 0) {
    description = `Positive ${formatted}`;
  } else {
    description = `Negative ${formatted}`;
  }
  return label ? `${label}: ${description}` : description;
}