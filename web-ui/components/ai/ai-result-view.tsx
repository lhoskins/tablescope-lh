"use client";

import {
  IconCheck,
  IconLoader2,
} from "@tabler/icons-react";
import { InsightChartBlock } from "@/components/tablescope/home/intelligence-card";
import type { InsightChart } from "@/lib/api/home-intelligence";
import type { SuggestedVisualization } from "@/lib/api/ai-actions";

export const PROGRESS_STEPS = [
  "Understanding question",
  "Selecting authorized data sources",
  "Building query",
  "Running query",
  "Formatting results",
] as const;

function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const n = Number(value.replace(/,/g, "").trim());
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export function isNumeric(value: unknown): boolean {
  return toNumber(value) !== null;
}

/** Build a renderable chart from result rows + the suggested visualization. */
export function buildChart(
  columns: string[],
  rows: Record<string, unknown>[],
  viz: SuggestedVisualization,
): InsightChart | null {
  if (!rows.length || !columns.length) return null;
  if (viz.type === "table") return null;

  if (viz.type === "kpi") {
    const field = viz.metricField ?? columns[0];
    const value = rows[0]?.[field];
    if (value == null) return null;
    return {
      type: "kpi_grid",
      data: { kpis: [{ value: String(value), label: field }] },
    };
  }

  const xField = viz.xField ?? columns[0];
  const yField = viz.yField ?? columns[1] ?? columns[0];
  let series = rows
    .map((r) => ({
      label: String(r[xField] ?? ""),
      value: toNumber(r[yField]) ?? 0,
    }))
    .filter((s) => s.label !== "");
  if (!series.length) return null;

  // Keep the family the engine chose. Collapsing everything to pie/line/bar
  // here silently undid the shared ask pipeline's chart-fit ranking — a scatter
  // or heatmap answer came back as a bar. The renderer (EChartsWidget, via
  // WidgetRenderer) draws every family in the vocabulary, so pass it through.
  const type = viz.type as InsightChart["type"];

  // Bars with many categories are ranked by the measure and capped to the top N
  // (the engine's decision) so the chart shows the leaders instead of an
  // unreadable wall of ticks; the full result stays in the table below.
  if (type === "bar") {
    const cap = viz.topN ?? 25;
    if (series.length > cap) {
      series = [...series].sort((a, b) => b.value - a.value).slice(0, cap);
    }
  } else {
    series = series.slice(0, 25);
  }

  const subtype = viz.chartStyle || undefined;
  return { type, subtype, data: { series }, seriesLabels: { value: yField } };
}

export function ResultChart({
  columns,
  rows,
  viz,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  viz: SuggestedVisualization;
}) {
  const chart = buildChart(columns, rows, viz);
  if (!chart) return null;
  return (
    <div className="mb-3 rounded-md border border-line-tertiary p-3">
      <InsightChartBlock chart={chart} />
    </div>
  );
}

export function rankVisualizations(
  columns: string[],
  rows: Record<string, unknown>[],
  defaultViz?: SuggestedVisualization,
): { viz: SuggestedVisualization; label: string }[] {
  if (!columns.length || !rows.length) {
    return [{ viz: { type: "table" }, label: "Table" }];
  }
  const numericCols = columns.filter(
    (c) =>
      rows.filter((r) => isNumeric(r[c])).length >= Math.max(1, rows.length / 2),
  );
  const valueCol = numericCols[0];
  const labelCol = columns.find((c) => c !== valueCol) ?? columns[0];
  const candidates: { viz: SuggestedVisualization; label: string }[] = [
    { viz: { type: "table" }, label: "Table" },
  ];
  if (rows.length === 1 && valueCol) {
    candidates.push({
      viz: { type: "kpi", metricField: valueCol },
      label: "KPI",
    });
  }
  if (valueCol && columns.length >= 2) {
    const base = { xField: labelCol, yField: valueCol };
    candidates.push({ viz: { type: "bar", ...base }, label: "Bar" });
    candidates.push({ viz: { type: "line", ...base }, label: "Line" });
    candidates.push({ viz: { type: "pie", ...base }, label: "Pie" });
  }
  if (defaultViz) {
    const existing = candidates.find((c) => c.viz.type === defaultViz.type);
    if (existing) {
      candidates.splice(candidates.indexOf(existing), 1);
      candidates.unshift(existing);
    } else {
      candidates.unshift({
        viz: defaultViz,
        label: defaultViz.type[0].toUpperCase() + defaultViz.type.slice(1),
      });
    }
  }
  return candidates;
}

export function ChartOptions({
  columns,
  rows,
  value,
  onChange,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  value: SuggestedVisualization;
  onChange: (viz: SuggestedVisualization) => void;
}) {
  const candidates = rankVisualizations(columns, rows, value);
  return (
    <label className="flex items-center gap-2 text-[12px] text-ink-secondary">
      Chart options:
      <select
        value={value.type}
        onChange={(event) => {
          const selected = candidates.find((c) => c.viz.type === event.target.value);
          if (selected) onChange(selected.viz);
        }}
        className="h-7 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none"
      >
        {candidates.map((candidate) => (
          <option key={candidate.viz.type} value={candidate.viz.type}>
            {candidate.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ResultTable({
  columns,
  rows,
  total,
  page = 0,
  pageSize = 100,
  onPageChange,
  loading,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  loading?: boolean;
}) {
  if (!columns.length) return null;
  const rowTotal = total ?? rows.length;
  const hasRows = rowTotal > 0;
  const pageCount = Math.max(1, Math.ceil(rowTotal / pageSize));
  const start = page * pageSize + 1;
  const end = Math.min((page + 1) * pageSize, rowTotal);
  const displayRows = onPageChange ? rows : rows.slice(page * pageSize, (page + 1) * pageSize);

  return (
    <div className="rounded-md border border-line-tertiary">
      <div className="max-h-[320px] overflow-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 bg-bg-secondary">
            <tr>
              {columns.map((c) => (
                <th
                  key={c}
                  className="border-b border-line-tertiary px-2 py-1.5 text-left font-medium text-ink-secondary"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, ri) => (
              <tr key={ri}>
                {columns.map((c) => (
                  <td
                    key={c}
                    className="border-b border-line-tertiary/60 px-2 py-1.5 text-ink-primary"
                  >
                    {row[c] == null ? "" : String(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!hasRows && !loading && (
        <p className="py-6 text-center text-[13px] text-ink-tertiary">
          The query ran but returned no rows.
        </p>
      )}
      {hasRows && onPageChange && (
        <div className="flex items-center justify-between gap-2 border-t border-line-tertiary px-3 py-2 text-[12px] text-ink-secondary">
          <span>
            {start}-{end} of {rowTotal}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 0 || loading}
              onClick={() => onPageChange(page - 1)}
              className="rounded-md border border-line-secondary px-2 py-1 text-xs disabled:opacity-50"
            >
              Previous
            </button>
            <span>
              Page {page + 1} of {pageCount}
            </span>
            <button
              type="button"
              disabled={page >= pageCount - 1 || loading}
              onClick={() => onPageChange(page + 1)}
              className="rounded-md border border-line-secondary px-2 py-1 text-xs disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ProgressSteps({ activeIndex }: { activeIndex: number }) {
  return (
    <ul className="space-y-2 py-2">
      {PROGRESS_STEPS.map((label, i) => {
        const done = i < activeIndex;
        const active = i === activeIndex;
        return (
          <li key={label} className="flex items-center gap-2 text-[13px]">
            {done ? (
              <IconCheck size={15} className="text-success" />
            ) : active ? (
              <IconLoader2 size={15} className="animate-spin text-brand-500" />
            ) : (
              <span className="h-[15px] w-[15px] rounded-full border border-line-secondary" />
            )}
            <span
              className={
                done
                  ? "text-ink-secondary"
                  : active
                    ? "text-ink-primary"
                    : "text-ink-tertiary"
              }
            >
              {label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
