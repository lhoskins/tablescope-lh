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
} from "@tabler/icons-react";import { TITLE_WIDTH } from "./percent-change-summary-table/title-width";
import { PERIOD_WIDTH } from "./percent-change-summary-table/period-width";
import { STAT_WIDTH } from "./percent-change-summary-table/stat-width";
import { OVERSCAN } from "./percent-change-summary-table/overscan";
import { STAT_COUNT } from "./percent-change-summary-table/stat-count";
import { STAT_FIELDS } from "./percent-change-summary-table/stat-fields";
import { STAT_LABELS } from "./percent-change-summary-table/stat-labels";
import { STAT_TOOLTIPS } from "./percent-change-summary-table/stat-tooltips";
import { ariaSortValue } from "./percent-change-summary-table/aria-sort-value";
import { signedCellClasses } from "./percent-change-summary-table/signed-cell-classes";
import { valueAriaLabel } from "./percent-change-summary-table/value-aria-label";
import { cellTooltip } from "./percent-change-summary-table/cell-tooltip";
import { FALLBACK_CELL } from "./percent-change-summary-table/fallback-cell";
import { StatCell } from "./percent-change-summary-table/stat-cell";
import { PercentChangeSummaryTableProps } from "./percent-change-summary-table/percent-change-summary-table-props";



export function PercentChangeSummaryTable({
  periods,
  rows,
  sort,
  onSort,
  showStatistics = true,
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

  const totalColumns = 1 + totalPeriods + (showStatistics ? STAT_COUNT : 0);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-tertiary">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded bg-[#74C990]" aria-hidden />
          Positive
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded bg-[#EA7975]" aria-hidden />
          Negative
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-flex h-3 w-3 items-center justify-center rounded bg-[#626365] text-[9px] text-white" aria-hidden>
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
            {showStatistics && (
              <col
                span={STAT_COUNT}
                style={{ width: STAT_WIDTH, minWidth: STAT_WIDTH }}
              />
            )}
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
              {showStatistics && (
                <th
                  colSpan={STAT_COUNT}
                  scope="colgroup"
                  className="border-b border-line-tertiary border-l-2 border-line-secondary p-2 text-center text-[12px] font-medium text-ink-secondary"
                >
                  Period Statistics
                </th>
              )}
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
              {showStatistics && STAT_FIELDS.map((field) => (
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
                {showStatistics && STAT_FIELDS.map((field) => (
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
