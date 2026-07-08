"use client";

import { useState } from "react";
import { IconChartBar, IconTable } from "@tabler/icons-react";
import { InsightChartBlock } from "@/components/tablescope/home/intelligence-card";
import type { DashboardWidgetSuggestion } from "@/lib/api/home-intelligence";

/**
 * A single generated-dashboard widget: chart with a "Show data" toggle and an
 * optional plain-English explanation. Shared by the Generate Dashboard modal's
 * legacy body and the unified {@link ResponsePresenter} `chart_cards` section so
 * both render identically.
 */
export function DashboardWidgetCard({
  widget,
}: {
  widget: DashboardWidgetSuggestion;
}) {
  const [showData, setShowData] = useState(false);
  const series = widget.chart?.data?.series ?? [];
  const kpis = widget.chart?.data?.kpis ?? [];
  const canShowData = series.length > 0 || kpis.length > 0;

  return (
    <div className="rounded-md border border-line-tertiary bg-bg-secondary/40 p-3">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0 text-small font-medium text-ink-primary">
          {widget.title}
        </div>
        {canShowData && (
          <button
            type="button"
            onClick={() => setShowData((v) => !v)}
            className="flex shrink-0 items-center gap-1 text-[12px] text-ink-tertiary hover:text-ink-secondary"
          >
            {showData ? (
              <>
                <IconChartBar size={13} /> Chart
              </>
            ) : (
              <>
                <IconTable size={13} /> Show data
              </>
            )}
          </button>
        )}
      </div>
      {showData && canShowData ? (
        <WidgetDataTable widget={widget} />
      ) : (
        <InsightChartBlock chart={widget.chart} />
      )}
      {widget.explanation && (
        <p className="mt-2 text-[12px] leading-relaxed text-ink-secondary">
          {widget.explanation}
        </p>
      )}
    </div>
  );
}

/** Format a numeric metric value per its detected format (mirrors the backend). */
function formatValue(v: number, fmt?: string): string {
  if (fmt === "percent") {
    const pct = Math.abs(v) <= 1 ? v * 100 : v;
    return `${pct.toFixed(1)}%`;
  }
  if (fmt === "currency") return `$${v.toLocaleString()}`;
  if (fmt === "count") return Math.round(v).toLocaleString();
  return v.toLocaleString();
}

function WidgetDataTable({ widget }: { widget: DashboardWidgetSuggestion }) {
  const series = widget.chart?.data?.series ?? [];
  const kpis = widget.chart?.data?.kpis ?? [];
  const metric = widget.valueColumn || "Value";
  const dimension = widget.labelColumn || "Category";

  if (series.length === 0 && kpis.length > 0) {
    return (
      <div className="max-h-[180px] overflow-auto">
        <table className="w-full text-[12px]">
          <tbody>
            {kpis.map((k, i) => (
              <tr key={i} className="border-b border-line-tertiary/60">
                <td className="py-1 pr-2 text-ink-secondary">{k.label}</td>
                <td className="py-1 text-right font-medium text-ink-primary">
                  {k.value}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="max-h-[180px] overflow-auto">
      <table className="w-full text-[12px]">
        <thead className="sticky top-0 bg-bg-secondary">
          <tr className="text-left text-ink-tertiary">
            <th className="py-1 pr-2 font-medium">{dimension}</th>
            <th className="py-1 text-right font-medium">{metric}</th>
          </tr>
        </thead>
        <tbody>
          {series.map((s, i) => (
            <tr key={i} className="border-b border-line-tertiary/60">
              <td className="py-1 pr-2 text-ink-secondary" title={s.label}>
                {s.label}
              </td>
              <td className="py-1 text-right font-medium text-ink-primary">
                {formatValue(s.value, widget.format)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
