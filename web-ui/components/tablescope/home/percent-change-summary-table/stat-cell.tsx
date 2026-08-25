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
} from "@tabler/icons-react";import { STAT_LABELS } from "./stat-labels";
import { STAT_TOOLTIPS } from "./stat-tooltips";
import { SIGNED_STAT_FIELDS } from "./signed-stat-fields";
import { signedCellClasses } from "./signed-cell-classes";
import { valueAriaLabel } from "./value-aria-label";



export function StatCell({
  field,
  value,
  presentation = "default",
}: {
  field: keyof PercentChangeSummaryStatistics;
  value: number | null;
  presentation?: "default" | "executive";
}) {
  const isSigned = SIGNED_STAT_FIELDS.has(field);
  const isNeutral = field === "standard_deviation" || field === "valid_count";
  const displayValue =
    value === null || value === undefined
      ? null
      : field === "valid_count"
        ? value
        : value;

  const formatted =
    displayValue === null || displayValue === undefined
      ? "-"
      : field === "valid_count"
        ? String(displayValue)
        : formatPercentChange(displayValue);

  const className = cn(
    "p-2 text-center align-top",
    isSigned ? signedCellClasses(displayValue, presentation) : "text-ink-secondary",
  );

  const ariaLabel =
    field === "valid_count"
      ? `${STAT_LABELS[field]}: ${displayValue ?? "No data"}`
      : valueAriaLabel(displayValue, STAT_LABELS[field]);

  return (
    <td
      className={className}
      title={STAT_TOOLTIPS[field]}
      aria-label={ariaLabel}
    >
      <span aria-hidden>{formatted}</span>
    </td>
  );
}