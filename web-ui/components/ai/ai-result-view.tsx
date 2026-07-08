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
  const series = rows
    .slice(0, 25)
    .map((r) => ({
      label: String(r[xField] ?? ""),
      value: toNumber(r[yField]) ?? 0,
    }))
    .filter((s) => s.label !== "");
  if (!series.length) return null;

  const type = viz.type === "pie" ? "pie" : viz.type === "line" ? "line" : "bar";
  return { type, data: { series }, seriesLabels: { value: yField } };
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

export function ResultTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
}) {
  if (!columns.length || !rows.length) {
    return (
      <p className="py-6 text-center text-[13px] text-ink-tertiary">
        The query ran but returned no rows.
      </p>
    );
  }
  return (
    <div className="max-h-[320px] overflow-auto rounded-md border border-line-tertiary">
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
          {rows.slice(0, 100).map((row, ri) => (
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
