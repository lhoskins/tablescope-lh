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
} from "@tabler/icons-react";


export function cellTooltip(
  row: PercentChangeSummaryRow,
  period: PercentChangeSummaryPeriod,
  cell: PercentChangeSummaryCell,
): string {
  const parts = [`${row.title}, ${row.project_name}, ${period.label}`];
  if (cell.percent_change_ratio !== null && cell.percent_change_ratio !== undefined) {
    const direction =
      cell.percent_change_ratio > 0
        ? "increased"
        : cell.percent_change_ratio < 0
          ? "decreased"
          : "changed";
    parts.push(
      `${direction} ${formatPercentChange(cell.percent_change_ratio)} from ${cell.previous_value ?? "No data"} to ${cell.current_value ?? "No data"}`,
    );
  } else {
    parts.push("No data");
  }
  if (cell.comparison_status && cell.comparison_status !== "unavailable") {
    parts.push(`Status: ${cell.comparison_status}`);
  }
  if (cell.partial) {
    parts.push("Partial period");
  }
  if (cell.warnings?.length) {
    parts.push(...cell.warnings);
  }
  if (row.data_through) {
    parts.push(`Data through ${row.data_through}`);
  }
  return parts.join("; ");
}