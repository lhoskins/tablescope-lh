"use client";

import { useCallback, useMemo } from "react";
import { IconChartBar, IconTrash } from "@tabler/icons-react";
import { Card } from "@/components/ui/card";
import { WidgetRenderer } from "./WidgetRenderer";
import type { WidgetConfig, ChartClickEvent } from "./types";
// Shared operational-insight visual grammar — built for the ITSM insight
// dashboards but structurally domain-agnostic (CSS grid layout, the chart
// renderer's option-building, the metric-card shape), so it's reused here
// as-is rather than re-approximated. This is deliberate: the generic
// WidgetRenderer/EChartsWidget engine every other dashboard uses has its
// own different chart defaults (vertical bars, a heavier line-area fill) —
// close in spirit but not the actual ServiceNow look. Only ItsmChart
// produces skinny horizontal bars with end labels and the specific subtle
// (10%-opacity, first-series-only) area fill the real screens use, so an
// AI-Designer dashboard of any domain renders through it too.
import styles from "@/components/tablescope/project/itsm-dashboards/ItsmDashboardScreen.module.css";
import { ItsmChart as OperationalChart } from "@/components/tablescope/project/itsm-dashboards/ItsmChart";
import type {
  ItsmChart as OperationalChartData,
  ItsmChartSeries,
} from "@/components/tablescope/project/itsm-dashboards/types";
import {
  OperationalBriefStrip,
  toOperationalStories,
  type OperationalNarrativeItem,
} from "@/components/tablescope/project/operational-dashboard-shell";

export { OperationalChart };
export type { OperationalChartData };

interface OperationalNarrativeWidget {
  id?: string;
  type?: string;
  title?: string;
  summary?: string;
  // The designer emits structured `{label, detail, tone}` brief items;
  // dashboards saved earlier hold plain strings. Both render (see
  // `toOperationalStories`), so no migration is required.
  items?: Array<string | OperationalNarrativeItem>;
}

function narrativeText(item: string | OperationalNarrativeItem): string {
  return typeof item === "string" ? item : item.detail || item.label || "";
}

const EDIT_ICON = (
  <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
    />
  </svg>
);

function findNarrative(
  operationalWidgets: OperationalNarrativeWidget[],
  type: string,
): OperationalNarrativeWidget | undefined {
  return operationalWidgets.find((w) => w.type === type);
}

function toNumber(value: unknown): number | null {
  const num = typeof value === "number" ? value : Number(value);
  return Number.isFinite(num) ? num : null;
}

function niceName(column: string): string {
  return column.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Adapts a dashboard widget + its fetched rows into the shape ItsmChart
 *  renders, so any AI-Designer chart gets the exact ServiceNow chart
 *  styling rather than an approximation of it. Pivots into one series per
 *  distinct value of groupByColumn when the widget uses one (e.g. "Opened"
 *  vs "Resolved" on the same axis); builds a two-series comparison from
 *  yColumn + y2Column for a combo widget (e.g. actual vs forecast, the
 *  shape visualization_engine.rank_visualizations already ranks ChartType
 *  .COMBO for); otherwise a single named series. */
export function toOperationalChartData(
  widget: WidgetConfig,
  rows: Array<Record<string, unknown>>,
): OperationalChartData {
  const xKey = widget.xColumn || widget.xKey || "";
  const yKey = widget.yColumn || widget.yKey || "";
  const groupKey = widget.groupByColumn;

  let categories: string[];
  let series: ItsmChartSeries[];

  if (widget.type === "combo" && widget.y2Column) {
    const x = rows.map((row) => String(row[xKey] ?? ""));
    categories = x;
    series = [
      { name: niceName(widget.yColumn || yKey || "Value"), x, y: rows.map((row) => toNumber(row[yKey])) },
      { name: niceName(widget.y2Column), x, y: rows.map((row) => toNumber(row[widget.y2Column!])) },
    ];
  } else if (groupKey && rows.length > 0 && Object.keys(rows[0]).includes(groupKey)) {
    const xValues: string[] = [];
    const byGroup = new Map<string, Map<string, number | null>>();
    for (const row of rows) {
      const x = String(row[xKey] ?? "");
      const group = String(row[groupKey] ?? "Other");
      if (!xValues.includes(x)) xValues.push(x);
      if (!byGroup.has(group)) byGroup.set(group, new Map());
      byGroup.get(group)!.set(x, toNumber(row[yKey]));
    }
    categories = xValues;
    series = Array.from(byGroup.entries()).map(([name, valuesByX]) => ({
      name,
      x: xValues,
      y: xValues.map((x) => valuesByX.get(x) ?? null),
    }));
  } else {
    const x = rows.map((row) => String(row[xKey] ?? ""));
    const y = rows.map((row) => toNumber(row[yKey]));
    categories = x;
    series = [{ name: widget.title || yKey || "Value", x, y }];
  }

  const chartType =
    widget.type === "bar"
      ? "skinny_bar"
      : widget.type === "combo"
        ? "combo"
        : widget.type === "pie"
          ? "pie"
          : widget.type === "heatmap"
            ? "heatmap"
            : "line";

  return {
    chartKey: widget.id,
    title: widget.title,
    chartType,
    xAxisLabel: null,
    yAxisLabel: widget.yColumn || null,
    series,
    categories,
    unit: null,
  };
}

/**
 * One chart card, as its own component rather than an inline-rendered
 * function, so `useMemo`/`useCallback` can keep the `ItsmChart` instance
 * stable across renders that don't actually change this widget's config or
 * data. Without that, every unrelated re-render of the parent grid (a
 * cross-filter click, another widget's data arriving, a dialog opening)
 * rebuilt the chart-data object and the click handler from scratch, which
 * forced `ItsmChart` to fully dispose and re-`echarts.init()` on every
 * tick -- harmless in isolation, but the visible symptom (flashing/frozen
 * chart) when combined with a render loop elsewhere.
 */
function OperationalChartCard({
  widget,
  rows,
  heightClass,
  onEditWidget,
  onChartOptions,
  onDeleteWidget,
  onElementClick,
}: {
  widget: WidgetConfig;
  rows: Array<Record<string, unknown>>;
  heightClass: string;
  onEditWidget: (widget: WidgetConfig) => void;
  onChartOptions?: (widget: WidgetConfig) => void;
  onDeleteWidget?: (widget: WidgetConfig) => void;
  onElementClick: (widget: WidgetConfig, event: ChartClickEvent) => void;
}) {
  const chartData = useMemo(() => toOperationalChartData(widget, rows), [widget, rows]);
  const handleElementClick = useCallback(
    (name: string, value: number | null) =>
      onElementClick(widget, {
        sourceField: widget.xColumn || widget.xKey || "",
        value: value ?? name,
        label: name,
      }),
    [widget, onElementClick],
  );

  return (
    <Card className="overflow-hidden p-3">
      <div className="mb-1 flex items-start justify-between gap-3">
        <h3 className="truncate text-small font-semibold text-ink-primary">
          {widget.title || "Untitled"}
        </h3>
        <div className="flex shrink-0 items-center gap-0.5">
          {onChartOptions && (
            <button
              type="button"
              onClick={() => onChartOptions(widget)}
              title="Chart options"
              className="rounded p-1 text-ink-tertiary transition-colors hover:bg-bg-secondary hover:text-ink-secondary"
            >
              <IconChartBar size={14} />
            </button>
          )}
          <button
            type="button"
            onClick={() => onEditWidget(widget)}
            title="Modify with AI"
            className="rounded p-1 text-ink-tertiary transition-colors hover:bg-bg-secondary hover:text-ink-secondary"
          >
            {EDIT_ICON}
          </button>
          {onDeleteWidget && (
            <button
              type="button"
              onClick={() => onDeleteWidget(widget)}
              title="Delete widget"
              className="rounded p-1 text-ink-tertiary transition-colors hover:bg-red-50 hover:text-red-600"
            >
              <IconTrash size={14} />
            </button>
          )}
        </div>
      </div>
      <div className={heightClass}>
        <OperationalChart chart={chartData} className="h-full" onElementClick={handleElementClick} />
      </div>
    </Card>
  );
}

/**
 * Curated operational-insight layout: brief, KPI grid, a main chart + side
 * stack, then a bottom row pairing charts with Best Improvement
 * Opportunities — the same structure `ItsmInsightsDashboardContent` uses,
 * generalized to any AI-Designer-created dashboard's widgets rather than
 * the bespoke ITSM data source. Rendered instead of the free-form
 * react-grid-layout widget grid when the dashboard carries the narrative
 * `operationalWidgets` the AI Designer already persists at creation time.
 */
export function OperationalInsightGrid({
  widgets,
  widgetData,
  operationalWidgets,
  onEditWidget,
  onElementClick,
  onChartOptions,
  onDeleteWidget,
}: {
  widgets: WidgetConfig[];
  widgetData: Record<string, Array<Record<string, unknown>>>;
  operationalWidgets: OperationalNarrativeWidget[];
  onEditWidget: (widget: WidgetConfig) => void;
  onElementClick: (widget: WidgetConfig, event: ChartClickEvent) => void;
  /** Opens the lightweight "pick a compatible chart type" picker, reusing
   *  the same ranking Business Insight cards use, as an alternative to a
   *  full AI re-design via `onEditWidget`. */
  onChartOptions?: (widget: WidgetConfig) => void;
  /** Removes the widget from the dashboard entirely. */
  onDeleteWidget?: (widget: WidgetConfig) => void;
}) {
  const brief = findNarrative(operationalWidgets, "operational_brief");
  const improvements = findNarrative(operationalWidgets, "improvement_opportunities");

  const kpiWidgets = widgets.filter((w) => w.type === "kpi");
  const chartWidgets = widgets.filter((w) => w.type !== "kpi");
  const [mainChart, ...restCharts] = chartWidgets;
  const sideCharts = restCharts.slice(0, 2);
  const bottomCharts = restCharts.slice(2, 4);
  const overflowCharts = restCharts.slice(4);

  const chartCard = (widget: WidgetConfig, heightClass: string) => (
    <OperationalChartCard
      key={widget.id}
      widget={widget}
      rows={widgetData[widget.id] ?? []}
      heightClass={heightClass}
      onEditWidget={onEditWidget}
      onChartOptions={onChartOptions}
      onDeleteWidget={onDeleteWidget}
      onElementClick={onElementClick}
    />
  );

  return (
    <div className={styles.dashboardContainer}>
      {brief && (
        <OperationalBriefStrip
          stories={toOperationalStories(brief.items, brief.summary)}
          subtitle={brief.summary || "The story behind the selected period"}
        />
      )}

      {kpiWidgets.length > 0 && (
        <div className={`${styles.kpiGrid} mt-3`}>
          {kpiWidgets.map((widget) => (
            <div key={widget.id} className={styles.cardStandard}>
              <Card className="h-full p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="truncate text-[11px] font-semibold uppercase tracking-[0.02em] text-ink-secondary">
                    {widget.title}
                  </span>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button
                      type="button"
                      onClick={() => onEditWidget(widget)}
                      title="Modify with AI"
                      className="rounded p-0.5 text-ink-tertiary hover:bg-bg-secondary"
                    >
                      {EDIT_ICON}
                    </button>
                    {onDeleteWidget && (
                      <button
                        type="button"
                        onClick={() => onDeleteWidget(widget)}
                        title="Delete widget"
                        className="rounded p-0.5 text-ink-tertiary hover:bg-red-50 hover:text-red-600"
                      >
                        <IconTrash size={14} />
                      </button>
                    )}
                  </div>
                </div>
                <WidgetRenderer
                  widget={widget}
                  data={widgetData[widget.id] ?? []}
                  operational
                  onElementClick={(event) => onElementClick(widget, event)}
                />
              </Card>
            </div>
          ))}
        </div>
      )}

      {mainChart && (
        <div className={`${styles.insightMainGrid} mt-3`}>
          {chartCard(mainChart, "h-72")}
          <div className={styles.insightSideStack}>
            {sideCharts.map((widget) => chartCard(widget, "h-52"))}
          </div>
        </div>
      )}

      {(bottomCharts.length > 0 || improvements) && (
        <div className={`${styles.insightBottomGrid} mt-3`}>
          {bottomCharts.map((widget) => chartCard(widget, "h-56"))}
          {improvements && (
            <Card className="p-4">
              <div className="text-sm font-semibold text-ink-primary">
                {improvements.title || "Best improvement opportunities"}
              </div>
              <div className="mt-1 text-[11px] text-ink-tertiary">
                Prioritized by operational impact
              </div>
              <div className="mt-4 space-y-3">
                {(improvements.items ?? []).map((item, index) => (
                  <div
                    key={index}
                    className="flex items-start justify-between gap-3 border-b border-line-tertiary pb-3 text-left last:border-0"
                  >
                    <span className="block text-xs font-semibold text-ink-primary">
                      {index + 1}. {narrativeText(item)}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {overflowCharts.length > 0 && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {overflowCharts.map((widget) => chartCard(widget, "h-56"))}
        </div>
      )}
    </div>
  );
}
