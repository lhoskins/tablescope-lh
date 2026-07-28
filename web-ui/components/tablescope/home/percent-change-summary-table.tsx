"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { formatPercentChange } from "@/lib/insights/time-series";
import { insightAnchorId } from "@/lib/insights/return-target";
import type {
  PercentChangeSummaryCell,
  PercentChangeSummaryPeriod,
  PercentChangeSummaryRow,
  PercentChangeSummarySort,
} from "@/lib/api/home-intelligence";
import {
  IconArrowUp,
  IconArrowDown,
  IconChevronLeft,
  IconChevronRight,
} from "@tabler/icons-react";

const DEFAULT_WINDOW_SIZE = 12;

function ariaSortValue(
  direction: "asc" | "desc" | undefined,
): "none" | "ascending" | "descending" {
  if (direction === "asc") return "ascending";
  if (direction === "desc") return "descending";
  return "none";
}

function usePeriodWindow(total: number, size = DEFAULT_WINDOW_SIZE) {
  const [start, setStart] = useState(Math.max(0, total - size));

  const end = Math.min(total, start + size);
  const canPrev = start > 0;
  const canNext = end < total;

  const prev = () => setStart((s) => Math.max(0, s - size));
  const next = () =>
    setStart((s) => Math.min(Math.max(0, total - size), s + size));

  return { start, end, canPrev, canNext, prev, next };
}

function cellTooltip(
  row: PercentChangeSummaryRow,
  period: PercentChangeSummaryPeriod,
  cell: PercentChangeSummaryCell,
): string {
  const parts = [
    `${row.title}, ${row.project_name}, ${period.label}`,
  ];
  if (cell.percent_change_ratio !== null) {
    const direction = cell.percent_change_ratio > 0 ? "increased" : cell.percent_change_ratio < 0 ? "decreased" : "changed";
    parts.push(
      `${direction} ${formatPercentChange(cell.percent_change_ratio)} from ${cell.previous_value ?? "N/A"} to ${cell.current_value ?? "N/A"}`,
    );
  } else {
    parts.push("N/A");
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

function CellContent({ cell }: { cell: PercentChangeSummaryCell }) {
  if (cell.percent_change_ratio === null) {
    return <span className="text-ink-tertiary">N/A</span>;
  }
  const formatted = formatPercentChange(cell.percent_change_ratio);
  const isPositive = cell.status === "positive";
  const isNegative = cell.status === "negative";
  const isZero = cell.status === "zero";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 font-medium",
        isPositive && "text-success",
        isNegative && "text-error",
        isZero && "text-ink-secondary",
      )}
      aria-label={formatted}
    >
      {isPositive && <IconArrowUp size={14} aria-hidden />}
      {isNegative && <IconArrowDown size={14} aria-hidden />}
      {formatted}
    </span>
  );
}

interface PercentChangeSummaryTableProps {
  periods: PercentChangeSummaryPeriod[];
  rows: PercentChangeSummaryRow[];
  sort: PercentChangeSummarySort;
  onSort: (sort: PercentChangeSummarySort) => void;
}

export function PercentChangeSummaryTable({
  periods,
  rows,
  sort,
  onSort,
}: PercentChangeSummaryTableProps) {
  const { start, end, canPrev, canNext, prev, next } = usePeriodWindow(
    periods.length,
  );
  const visiblePeriods = useMemo(
    () => periods.slice(start, end),
    [periods, start, end],
  );

  const handleTitleSort = () => {
    onSort({
      field: "title",
      direction: sort.field === "title" && sort.direction === "asc" ? "desc" : "asc",
    });
  };

  const handlePeriodSort = (key: string) => {
    const isCurrent = sort.field === `period:${key}`;
    onSort({
      field: `period:${key}`,
      direction: isCurrent && sort.direction === "desc" ? "asc" : "desc",
    });
  };

  const handleRowClick = (insightId: string) => {
    if (typeof window === "undefined") return;
    window.location.hash = insightAnchorId(insightId);
    const el = document.getElementById(insightAnchorId(insightId));
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.focus({ preventScroll: true });
  };

  return (
    <div className="overflow-x-auto" role="region" aria-label="Percent change summary table">
      <table className="w-full border-collapse text-[13px]">
        <caption className="sr-only">
          Percent change summary by insight and period
        </caption>
        <thead>
          <tr>
            <th
              scope="col"
              className="sticky left-0 z-10 w-56 min-w-56 bg-bg-primary p-2 text-left font-medium text-ink-secondary"
              aria-sort={ariaSortValue(sort.field === "title" ? sort.direction : undefined)}
            >
              <button
                type="button"
                onClick={handleTitleSort}
                className="flex w-full items-center gap-1 text-left font-medium"
              >
                Insight
                {sort.field === "title" &&
                  (sort.direction === "asc" ? (
                    <IconArrowUp size={14} />
                  ) : (
                    <IconArrowDown size={14} />
                  ))}
              </button>
            </th>
            {visiblePeriods.map((period) => (
              <th
                key={period.key}
                scope="col"
                className={cn(
                  "min-w-[96px] p-2 text-center font-medium text-ink-secondary",
                  period.is_latest && "text-ink-primary",
                )}
                aria-sort={ariaSortValue(
                  sort.field === `period:${period.key}` ? sort.direction : undefined,
                )}
              >
                <button
                  type="button"
                  onClick={() => handlePeriodSort(period.key)}
                  className="flex w-full flex-col items-center gap-0.5"
                >
                  <span className={cn(period.is_latest && "font-semibold")}>
                    {period.label}
                  </span>
                  {sort.field === `period:${period.key}` &&
                    (sort.direction === "asc" ? (
                      <IconArrowUp size={12} />
                    ) : (
                      <IconArrowDown size={12} />
                    ))}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.insight_id} className="border-t border-line-tertiary">
              <td className="sticky left-0 z-10 w-56 min-w-56 bg-bg-primary p-2 align-top">
                <button
                  type="button"
                  onClick={() => handleRowClick(row.insight_id)}
                  className="text-left"
                >
                  <div className="flex items-center gap-2">
                    {row.project_color && (
                      <span
                        className="inline-block h-2 w-2 rounded-full"
                        style={{ backgroundColor: row.project_color }}
                        aria-hidden
                      />
                    )}
                    <span className="font-medium text-ink-primary hover:text-brand-600 hover:underline">
                      {row.title}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink-tertiary">
                    {row.project_name}
                  </div>
                </button>
              </td>
              {visiblePeriods.map((period) => {
                const cell = row.cells[period.key] ?? {
                  current_value: null,
                  previous_value: null,
                  percent_change_ratio: null,
                  status: "unavailable",
                  comparison_status: "unavailable",
                  partial: false,
                  warnings: [],
                };
                return (
                  <td
                    key={period.key}
                    className="p-2 text-center align-top"
                    title={cellTooltip(row, period, cell)}
                  >
                    <CellContent cell={cell} />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {periods.length > DEFAULT_WINDOW_SIZE && (
        <div className="mt-2 flex items-center justify-between text-[11px] text-ink-tertiary">
          <button
            type="button"
            onClick={prev}
            disabled={!canPrev}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-bg-tertiary disabled:opacity-50"
          >
            <IconChevronLeft size={14} /> Previous periods
          </button>
          <span aria-live="polite">
            Showing {start + 1}–{end} of {periods.length} periods
          </span>
          <button
            type="button"
            onClick={next}
            disabled={!canNext}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-bg-tertiary disabled:opacity-50"
          >
            Next periods <IconChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
