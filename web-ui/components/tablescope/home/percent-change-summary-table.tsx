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

const TITLE_WIDTH = 224;
const PERIOD_WIDTH = 88;
const STAT_WIDTH = 76;
const OVERSCAN = 5;
const STAT_COUNT = 8;

const ZERO_TOLERANCE = 1e-9;

const STAT_FIELDS: (keyof PercentChangeSummaryStatistics)[] = [
  "latest",
  "min",
  "max",
  "median",
  "average",
  "standard_deviation",
  "cumulative_change",
  "valid_count",
];

const STAT_LABELS: Record<keyof PercentChangeSummaryStatistics, string> = {
  latest: "Latest",
  min: "Min",
  max: "Max",
  median: "Median",
  average: "Avg",
  standard_deviation: "Std Dev",
  cumulative_change: "Cumulative",
  valid_count: "n",
};

const STAT_TOOLTIPS: Record<keyof PercentChangeSummaryStatistics, string> = {
  latest: "Last valid period-over-period change in chronological order",
  min: "Smallest valid period-over-period change",
  max: "Largest valid period-over-period change",
  median: "Median of valid period-over-period changes",
  average: "Arithmetic mean of valid period-over-period changes",
  standard_deviation: "Population standard deviation of valid period-over-period changes",
  cumulative_change: "First-to-last change; not a sum of period changes",
  valid_count: "Number of valid period-over-period comparisons",
};

const SIGNED_STAT_FIELDS = new Set<keyof PercentChangeSummaryStatistics>([
  "latest",
  "min",
  "max",
  "median",
  "average",
  "cumulative_change",
]);

function ariaSortValue(
  direction: "asc" | "desc" | undefined,
): "none" | "ascending" | "descending" {
  if (direction === "asc") return "ascending";
  if (direction === "desc") return "descending";
  return "none";
}

function signedCellClasses(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "text-ink-tertiary";
  if (Math.abs(ratio) <= ZERO_TOLERANCE) return "text-ink-secondary";
  if (ratio > 0) return "bg-success-bg text-success";
  return "bg-danger-bg text-danger";
}

function valueAriaLabel(
  ratio: number | null | undefined,
  label?: string,
): string {
  if (ratio === null || ratio === undefined) {
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

function cellTooltip(
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

const FALLBACK_CELL: PercentChangeSummaryCell = {
  current_value: null,
  previous_value: null,
  percent_change_ratio: null,
  status: "unavailable",
  comparison_status: "unavailable",
  partial: false,
  warnings: [],
};

function StatCell({
  field,
  value,
}: {
  field: keyof PercentChangeSummaryStatistics;
  value: number | null;
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
    isSigned ? signedCellClasses(displayValue) : "text-ink-secondary",
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
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [clientWidth, setClientWidth] = useState(0);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () =>
      setClientWidth(
        el.clientWidth ||
          (typeof window !== "undefined" ? window.innerWidth : 0),
      );
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  const totalPeriods = periods.length;

  const { visibleStart, visibleEnd } = useMemo(() => {
    if (!clientWidth || totalPeriods === 0) {
      return { visibleStart: 0, visibleEnd: 0 };
    }
    const start = Math.max(
      0,
      Math.floor(scrollLeft / PERIOD_WIDTH) - OVERSCAN,
    );
    const end = Math.min(
      totalPeriods,
      Math.ceil((scrollLeft + clientWidth) / PERIOD_WIDTH) + OVERSCAN,
    );
    return { visibleStart: start, visibleEnd: end };
  }, [scrollLeft, clientWidth, totalPeriods]);

  const visiblePeriods = useMemo(
    () => periods.slice(visibleStart, visibleEnd),
    [periods, visibleStart, visibleEnd],
  );
  const hiddenBefore = visibleStart;
  const hiddenAfter = totalPeriods - visibleEnd;

  const handleTitleSort = () => {
    onSort({
      field: "title",
      direction:
        sort.field === "title" && sort.direction === "asc" ? "desc" : "asc",
    });
  };

  const handlePeriodSort = (key: string) => {
    const isCurrent = sort.field === `period:${key}`;
    onSort({
      field: `period:${key}`,
      direction: isCurrent && sort.direction === "desc" ? "asc" : "desc",
    });
  };

  const handleStatisticSort = (field: keyof PercentChangeSummaryStatistics) => {
    const isCurrent = sort.field === `statistics:${field}`;
    onSort({
      field: `statistics:${field}`,
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

  const totalColumns = 1 + totalPeriods + STAT_COUNT;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-tertiary">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded bg-success-bg text-success" aria-hidden />
          Positive
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded bg-danger-bg text-danger" aria-hidden />
          Negative
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-flex h-3 w-3 items-center justify-center rounded border border-line-tertiary bg-bg-primary text-[9px] text-ink-secondary" aria-hidden>
            0
          </span>
          No change
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-flex h-3 w-3 items-center justify-center rounded border border-line-tertiary bg-bg-primary text-[9px] text-ink-tertiary" aria-hidden>
            -
          </span>
          No data
        </span>
      </div>

      <div
        ref={containerRef}
        onScroll={(e) => setScrollLeft(e.currentTarget.scrollLeft)}
        className="overflow-x-auto"
        role="region"
        aria-label="Percent change summary table"
        tabIndex={0}
      >
        <table
          className="table-fixed border-collapse text-[13px]"
          aria-rowcount={rows.length + 1}
          aria-colcount={totalColumns}
        >
          <caption className="sr-only">
            Percent change summary by insight and period
          </caption>
          <colgroup>
            <col style={{ width: TITLE_WIDTH, minWidth: TITLE_WIDTH }} />
            <col
              span={Math.max(totalPeriods, 1)}
              style={{ width: PERIOD_WIDTH, minWidth: PERIOD_WIDTH }}
            />
            <col
              span={STAT_COUNT}
              style={{ width: STAT_WIDTH, minWidth: STAT_WIDTH }}
            />
          </colgroup>
          <thead>
            <tr>
              <th
                rowSpan={2}
                scope="col"
                className="sticky left-0 z-10 w-56 min-w-56 bg-bg-primary p-2 text-left font-medium text-ink-secondary"
              >
                <button
                  type="button"
                  onClick={handleTitleSort}
                  className="flex w-full items-center gap-1 text-left font-medium"
                >
                  Insight
                  {sort.field === "title" &&
                    (sort.direction === "asc" ? (
                      <IconArrowUp size={14} aria-hidden />
                    ) : (
                      <IconArrowDown size={14} aria-hidden />
                    ))}
                </button>
              </th>
              <th
                colSpan={totalPeriods}
                scope="colgroup"
                aria-hidden
                className="border-b border-line-tertiary p-0"
              />
              <th
                colSpan={STAT_COUNT}
                scope="colgroup"
                className="border-b border-line-tertiary border-l-2 border-line-secondary p-2 text-center text-[12px] font-medium text-ink-secondary"
              >
                Period Statistics
              </th>
            </tr>
            <tr>
              {hiddenBefore > 0 && (
                <th
                  colSpan={hiddenBefore}
                  aria-hidden
                  className="border-b border-line-tertiary p-0"
                />
              )}
              {visiblePeriods.map((period) => (
                <th
                  key={period.key}
                  scope="col"
                  className={cn(
                    "border-b border-line-tertiary p-2 text-center font-medium text-ink-secondary",
                    period.is_latest && "text-ink-primary",
                  )}
                  aria-sort={ariaSortValue(
                    sort.field === `period:${period.key}`
                      ? sort.direction
                      : undefined,
                  )}
                >
                  <button
                    type="button"
                    onClick={() => handlePeriodSort(period.key)}
                    className="flex w-full flex-col items-center gap-0.5"
                  >
                    <span
                      className={cn(
                        period.is_latest && "font-semibold",
                        "whitespace-nowrap",
                      )}
                    >
                      {period.label}
                    </span>
                    {sort.field === `period:${period.key}` &&
                      (sort.direction === "asc" ? (
                        <IconArrowUp size={12} aria-hidden />
                      ) : (
                        <IconArrowDown size={12} aria-hidden />
                      ))}
                  </button>
                </th>
              ))}
              {hiddenAfter > 0 && (
                <th
                  colSpan={hiddenAfter}
                  aria-hidden
                  className="border-b border-line-tertiary p-0"
                />
              )}
              {STAT_FIELDS.map((field) => (
                <th
                  key={field}
                  scope="col"
                  className={cn(
                    "border-b border-line-tertiary p-2 text-center text-[11px] font-medium text-ink-secondary",
                    field === "latest" && "border-l-2 border-line-secondary",
                  )}
                  aria-sort={ariaSortValue(
                    sort.field === `statistics:${field}`
                      ? sort.direction
                      : undefined,
                  )}
                  title={STAT_TOOLTIPS[field]}
                >
                  <button
                    type="button"
                    onClick={() => handleStatisticSort(field)}
                    className="flex w-full items-center justify-center gap-0.5 whitespace-nowrap"
                  >
                    {STAT_LABELS[field]}
                    {field === "cumulative_change" && (
                      <IconInfoCircle
                        size={12}
                        className="shrink-0 text-ink-tertiary"
                        aria-hidden
                      />
                    )}
                    {sort.field === `statistics:${field}` &&
                      (sort.direction === "asc" ? (
                        <IconArrowUp size={12} aria-hidden />
                      ) : (
                        <IconArrowDown size={12} aria-hidden />
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
                {hiddenBefore > 0 && (
                  <td
                    colSpan={hiddenBefore}
                    aria-hidden
                    className="border-t border-line-tertiary p-0"
                  />
                )}
                {visiblePeriods.map((period) => {
                  const cell = row.cells[period.key] ?? FALLBACK_CELL;
                  const ratio = cell.percent_change_ratio;
                  return (
                    <td
                      key={period.key}
                      className={cn(
                        "border-t border-line-tertiary p-2 text-center align-top",
                        signedCellClasses(ratio),
                      )}
                      title={cellTooltip(row, period, cell)}
                      aria-label={valueAriaLabel(ratio)}
                    >
                      <span aria-hidden>
                        {ratio === null || ratio === undefined
                          ? "-"
                          : formatPercentChange(ratio)}
                      </span>
                    </td>
                  );
                })}
                {hiddenAfter > 0 && (
                  <td
                    colSpan={hiddenAfter}
                    aria-hidden
                    className="border-t border-line-tertiary p-0"
                  />
                )}
                {STAT_FIELDS.map((field) => (
                  <StatCell
                    key={field}
                    field={field}
                    value={
                      (row.statistics[field] as number | null | undefined) ??
                      null
                    }
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
