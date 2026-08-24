"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { IconChartBar, IconTrash } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { Card } from "@/components/ui/card";
import { WidgetRenderer } from "./WidgetRenderer";
import type { WidgetConfig, ChartClickEvent, VisualizationOptions } from "./types";
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

// Bar subtypes that lay out horizontally -- mirrors the grid-placement check
// in the backend's `_widget_configs` (ai_proxy_dashboard_designer.py) so a
// chart classified as horizontal there for layout purposes renders
// horizontally here too. Anything else (the "column" default, "stacked_bar",
// "grouped_bar", "positive_negative", "waterfall", or no subtype at all) is
// vertical.
const HORIZONTAL_BAR_SUBTYPES = new Set([
  "horizontal_bar",
  "stacked_horizontal",
  "population_pyramid",
]);

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

  // Previously every "bar" widget was hard-mapped to "skinny_bar"
  // (horizontal) regardless of the subtype the user picked in the
  // chart-type picker, silently discarding that choice.
  const chartType =
    widget.type === "bar"
      ? HORIZONTAL_BAR_SUBTYPES.has(widget.chartSubtype ?? "")
        ? "skinny_bar"
        : "column"
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
    visualizationOptions: widget.visualizationOptions,
  };
}

/**
 * The chart itself -- data adaptation + click handler + `ItsmChart` --
 * without the surrounding Card/header chrome. Its own component (rather
 * than inlined) so `useMemo`/`useCallback` keep the `ItsmChart` instance
 * stable across renders that don't actually change this widget's config or
 * data; without that, every unrelated re-render of the parent grid (a
 * cross-filter click, another widget's data arriving, a dialog opening)
 * rebuilt the chart-data object and the click handler from scratch, which
 * forced `ItsmChart` to fully dispose and re-`echarts.init()` on every
 * tick -- harmless in isolation, but the visible symptom (flashing/frozen
 * chart) when combined with a render loop elsewhere.
 *
 * Exported so DashboardViewer's Edit Layout grid can render the exact same
 * ITSM-styled chart inside its own draggable/resizable grid item, instead
 * of falling back to the generic WidgetRenderer/EChartsWidget engine (which
 * has different chart defaults, e.g. vertical bars vs ItsmChart's
 * horizontal ones) and visibly changing the dashboard's appearance just
 * from entering edit mode.
 */
export function OperationalWidgetChart({
  widget,
  rows,
  className,
  onElementClick,
}: {
  widget: WidgetConfig;
  rows: Array<Record<string, unknown>>;
  className?: string;
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

  return <OperationalChart chart={chartData} className={className} onElementClick={handleElementClick} />;
}

const CARD_SIZE_CLASS: Record<NonNullable<VisualizationOptions["cardSize"]>, string> = {
  compact: styles.cardCompact,
  standard: styles.cardStandard,
  wide: styles.cardWide,
};
const CARD_SIZE_CYCLE: NonNullable<VisualizationOptions["cardSize"]>[] = ["compact", "standard", "wide"];
const CHART_HEIGHT_CLASS: Record<NonNullable<VisualizationOptions["chartHeight"]>, string> = {
  compact: "h-44",
  standard: "h-56",
  tall: "h-80",
};
const CHART_HEIGHT_CYCLE: NonNullable<VisualizationOptions["chartHeight"]>[] = ["compact", "standard", "tall"];

function sortByPosition(items: WidgetConfig[]): WidgetConfig[] {
  return [...items].sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
}

function cycle<T>(values: readonly T[], current: T): T {
  const index = values.indexOf(current);
  return values[(index + 1) % values.length];
}

/**
 * One flowing 12-column grid -- brief strip, then KPI cards and charts
 * interleaved in a single reorderable sequence, then Best Improvement
 * Opportunities -- ported directly from `ItsmDashboardContent`'s own
 * Edit Layout mechanism (native drag-and-drop reorder + a width/height
 * size cycle, position/size persisted on the widget itself) rather than
 * the generic react-grid-layout engine every other dashboard uses.
 *
 * This is deliberately the ONE layout this grid ever renders, in both
 * viewing and Edit Layout mode: a separate x/y/w/h grid model for editing
 * (as react-grid-layout requires) computed its own default positions
 * independently of this component's curated CSS-grid arrangement, so a
 * saved edit changed nothing here and a first-time (unedited) dashboard
 * didn't even look the same in the two modes. Driving both off the same
 * widget.position/visualizationOptions fields makes that impossible.
 */
export function OperationalInsightGrid({
  widgets,
  widgetData,
  operationalWidgets,
  editingLayout = false,
  onEditWidget,
  onElementClick,
  onChartOptions,
  onDeleteWidget,
  onLayoutChange,
}: {
  widgets: WidgetConfig[];
  widgetData: Record<string, Array<Record<string, unknown>>>;
  operationalWidgets: OperationalNarrativeWidget[];
  /** True while the dashboard is in Edit Layout mode -- enables
   *  drag-to-reorder and the width/height/size cycle controls. */
  editingLayout?: boolean;
  onEditWidget: (widget: WidgetConfig) => void;
  onElementClick: (widget: WidgetConfig, event: ChartClickEvent) => void;
  /** Opens the lightweight "pick a compatible chart type" picker, reusing
   *  the same ranking Business Insight cards use, as an alternative to a
   *  full AI re-design via `onEditWidget`. */
  onChartOptions?: (widget: WidgetConfig) => void;
  /** Removes the widget from the dashboard entirely. */
  onDeleteWidget?: (widget: WidgetConfig) => void;
  /** Fired with the full widget list (updated position/visualizationOptions)
   *  after a drag-reorder or a size-cycle click, so the caller can persist
   *  it -- the same fields this grid renders from in both view and edit
   *  mode, so a saved change is never invisible outside Edit Layout. */
  onLayoutChange?: (widgets: WidgetConfig[]) => void;
}) {
  const brief = findNarrative(operationalWidgets, "operational_brief");
  const improvements = findNarrative(operationalWidgets, "improvement_opportunities");

  // Local, immediately-updated copy for drag/resize feedback -- the
  // `widgets` prop only reflects a save after the mutation round-trips, so
  // waiting on it would make every drag/click feel like it did nothing
  // until the request resolved. Resynced whenever the prop itself changes
  // (widgets added/removed, or the eventual server-confirmed save).
  const [orderedWidgets, setOrderedWidgets] = useState<WidgetConfig[]>(() => sortByPosition(widgets));
  useEffect(() => {
    setOrderedWidgets(sortByPosition(widgets));
  }, [widgets]);

  const draggedId = useRef<string | null>(null);

  const applyOrder = useCallback(
    (next: WidgetConfig[]) => {
      const repositioned = next.map((w, index) => ({ ...w, position: index }));
      setOrderedWidgets(repositioned);
      onLayoutChange?.(repositioned);
    },
    [onLayoutChange],
  );

  const handleDrop = useCallback(
    (targetId: string) => {
      const sourceId = draggedId.current;
      draggedId.current = null;
      if (!sourceId || sourceId === targetId) return;
      const next = [...orderedWidgets];
      const from = next.findIndex((w) => w.id === sourceId);
      const to = next.findIndex((w) => w.id === targetId);
      if (from < 0 || to < 0) return;
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      applyOrder(next);
    },
    [orderedWidgets, applyOrder],
  );

  const updateVisualizationOptions = useCallback(
    (widgetId: string, patch: Partial<VisualizationOptions>) => {
      const next = orderedWidgets.map((w) =>
        w.id === widgetId ? { ...w, visualizationOptions: { ...w.visualizationOptions, ...patch } } : w,
      );
      setOrderedWidgets(next);
      onLayoutChange?.(next);
    },
    [orderedWidgets, onLayoutChange],
  );

  const chartIndexById = useMemo(() => {
    const map = new Map<string, number>();
    let index = 0;
    for (const w of orderedWidgets) {
      if (w.type === "kpi") continue;
      map.set(w.id, index);
      index += 1;
    }
    return map;
  }, [orderedWidgets]);

  const dragProps = (widgetId: string) => ({
    draggable: editingLayout,
    onDragStart: () => { draggedId.current = widgetId; },
    onDragOver: (event: DragEvent) => { if (editingLayout) event.preventDefault(); },
    onDrop: (event: DragEvent) => {
      if (!editingLayout) return;
      event.preventDefault();
      handleDrop(widgetId);
    },
  });

  return (
    <div className={styles.dashboardContainer}>
      {brief && (
        <OperationalBriefStrip
          stories={toOperationalStories(brief.items, brief.summary)}
          subtitle={brief.summary || "The story behind the selected period"}
        />
      )}

      {editingLayout && (
        <div className="mt-3 rounded-md border border-dashed border-brand-200 bg-brand-50/40 px-3 py-2 text-xs text-ink-secondary">
          Drag any card or chart into any grid position. Use the size controls to change chart width and height.
        </div>
      )}

      {orderedWidgets.length > 0 && (
        <div className={`${styles.kpiGrid} mt-3`}>
          {orderedWidgets.map((widget) => {
            if (widget.type === "kpi") {
              const size = widget.visualizationOptions?.cardSize ?? "standard";
              return (
                <div key={widget.id} className={CARD_SIZE_CLASS[size]} {...dragProps(widget.id)}>
                  <Card className={cn("h-full p-3", editingLayout && "cursor-grab border-dashed")}>
                    <div className="flex items-start justify-between gap-2">
                      <span className="truncate text-[11px] font-semibold uppercase tracking-[0.02em] text-ink-secondary">
                        {widget.title}
                      </span>
                      <div className="flex shrink-0 items-center gap-0.5">
                        {editingLayout && (
                          <button
                            type="button"
                            onClick={() => updateVisualizationOptions(widget.id, { cardSize: cycle(CARD_SIZE_CYCLE, size) })}
                            title="Resize"
                            className="rounded bg-bg-secondary px-1.5 py-0.5 text-[10px] font-semibold capitalize text-ink-secondary hover:bg-bg-tertiary"
                          >
                            {size}
                          </button>
                        )}
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
              );
            }

            // First chart defaults to prominent (full width, tall) to
            // approximate the old curated "main chart" hierarchy on a
            // never-edited dashboard; every explicit size is remembered
            // per widget once the user changes it.
            const chartIndex = chartIndexById.get(widget.id) ?? 0;
            const width = widget.visualizationOptions?.chartWidth ?? (chartIndex === 0 ? "full" : "half");
            const height = widget.visualizationOptions?.chartHeight ?? (chartIndex === 0 ? "tall" : "standard");
            return (
              <div
                key={widget.id}
                className={width === "full" ? styles.chartFull : styles.chartHalf}
                {...dragProps(widget.id)}
              >
                <Card className={cn("h-full overflow-hidden p-3", editingLayout && "cursor-grab border-dashed")}>
                  <div className="mb-1 flex items-start justify-between gap-3">
                    <h3 className="truncate text-small font-semibold text-ink-primary">
                      {widget.title || "Untitled"}
                    </h3>
                    <div className="flex shrink-0 items-center gap-0.5">
                      {editingLayout && (
                        <>
                          <button
                            type="button"
                            onClick={() =>
                              updateVisualizationOptions(widget.id, { chartWidth: width === "full" ? "half" : "full" })
                            }
                            title="Toggle width"
                            className="rounded bg-bg-secondary px-1.5 py-0.5 text-[10px] font-semibold text-ink-secondary hover:bg-bg-tertiary"
                          >
                            {width === "full" ? "Full" : "½"}
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              updateVisualizationOptions(widget.id, { chartHeight: cycle(CHART_HEIGHT_CYCLE, height) })
                            }
                            title="Cycle height"
                            className="rounded bg-bg-secondary px-1.5 py-0.5 text-[10px] font-semibold capitalize text-ink-secondary hover:bg-bg-tertiary"
                          >
                            {height}
                          </button>
                        </>
                      )}
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
                  <div className={CHART_HEIGHT_CLASS[height]}>
                    <OperationalWidgetChart
                      widget={widget}
                      rows={widgetData[widget.id] ?? []}
                      className="h-full"
                      onElementClick={onElementClick}
                    />
                  </div>
                </Card>
              </div>
            );
          })}
        </div>
      )}

      {improvements && (
        <Card className="mt-3 p-4">
          <div className="text-sm font-semibold text-ink-primary">
            {improvements.title || "Best improvement opportunities"}
          </div>
          <div className="mt-1 text-[11px] text-ink-tertiary">Prioritized by operational impact</div>
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
  );
}
