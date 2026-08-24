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
import denseGridStyles from "./OperationalInsightGrid.module.css";
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

const GRID_MIN_SPAN = 2;
const GRID_MAX_SPAN = 12;
const GRID_GAP_PX = 10; // matches .kpiGrid's `gap: 0.625rem` in the CSS module
const GRID_ROW_UNIT_PX = 8; // matches denseGridStyles.denseGrid's `grid-auto-rows: 8px`
const CHART_MIN_HEIGHT_PX = 160;
const CHART_MAX_HEIGHT_PX = 640;
const KPI_HEIGHT_PX = 96;
const KPI_MIN_HEIGHT_PX = 72;
const KPI_MAX_HEIGHT_PX = 320;

function sortByPosition(items: WidgetConfig[]): WidgetConfig[] {
  return [...items].sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** How many `GRID_ROW_UNIT_PX` row tracks (plus their gaps) a card needs to
 *  reach its target pixel height -- lets `grid-auto-flow: dense` treat a
 *  card's actual size as real, reservable grid space instead of every card
 *  implicitly spanning one row, which is what makes dense packing able to
 *  backfill a short card into the gap below another short one. */
export function rowSpanFor(heightPx: number): number {
  return Math.max(1, Math.round((heightPx + GRID_GAP_PX) / (GRID_ROW_UNIT_PX + GRID_GAP_PX)));
}

/** Default width/height for a widget that has never been explicitly
 *  resized -- the first chart defaults to prominent (full width, tall) to
 *  approximate the old curated "main chart" hierarchy on a never-edited
 *  dashboard; every explicit size is remembered per widget once the user
 *  drags it to one. */
function defaultSpan(widget: WidgetConfig, chartIndex: number): number {
  if (widget.type === "kpi") return 4;
  return chartIndex === 0 ? 12 : 6;
}

function defaultHeightPx(chartIndex: number): number {
  return chartIndex === 0 ? 320 : 224;
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

  const gridRef = useRef<HTMLDivElement>(null);
  const draggedId = useRef<string | null>(null);
  // Live values while a resize-handle drag is in progress, keyed by widget
  // id -- kept separate from `orderedWidgets` so dragging doesn't fire
  // `onLayoutChange` (and a save) on every pixel of mouse movement, only
  // once on release.
  const [resizePreview, setResizePreview] = useState<{ id: string; span: number; heightPx?: number } | null>(null);

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

  // Fallback for a drop that lands on genuinely empty grid space -- e.g. the
  // gap dense packing leaves open below a short card next to a tall one --
  // rather than on top of another card's own onDrop target. Moves the
  // dragged widget to the end of the order; dense packing then re-flows
  // everything and slots it into whatever gap the new order opens up.
  const handleContainerDrop = useCallback(
    (event: DragEvent) => {
      if (!editingLayout) return;
      if (event.target !== event.currentTarget) return; // a card's own onDrop already handled this
      event.preventDefault();
      const sourceId = draggedId.current;
      draggedId.current = null;
      if (!sourceId) return;
      const moved = orderedWidgets.find((w) => w.id === sourceId);
      if (!moved) return;
      applyOrder([...orderedWidgets.filter((w) => w.id !== sourceId), moved]);
    },
    [orderedWidgets, applyOrder, editingLayout],
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

  // Drag-to-resize from a handle in the card's bottom-right corner. Width
  // (a column count) always tracks horizontal movement; height (pixels)
  // only tracks vertical movement for charts -- KPI cards keep a fixed
  // height. Reads the grid's actual rendered width once, at drag start, to
  // convert a pixel delta into a column-count delta.
  const startResize = useCallback(
    (
        widget: WidgetConfig,
        startSpan: number,
        startHeightPx: number | undefined,
        resizeHeight: boolean,
        minHeightPx: number,
        maxHeightPx: number,
      ) =>
      (event: React.MouseEvent) => {
        event.preventDefault();
        event.stopPropagation();
        const gridWidthPx = gridRef.current?.getBoundingClientRect().width;
        if (!gridWidthPx) return;
        const columnStridePx = (gridWidthPx - 11 * GRID_GAP_PX) / 12 + GRID_GAP_PX;
        const startX = event.clientX;
        const startY = event.clientY;

        const onMove = (moveEvent: MouseEvent) => {
          const span = clamp(
            Math.round(startSpan + (moveEvent.clientX - startX) / columnStridePx),
            GRID_MIN_SPAN,
            GRID_MAX_SPAN,
          );
          const heightPx = resizeHeight && startHeightPx != null
            ? clamp(startHeightPx + (moveEvent.clientY - startY), minHeightPx, maxHeightPx)
            : undefined;
          setResizePreview({ id: widget.id, span, heightPx });
        };
        const onUp = () => {
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          setResizePreview((current) => {
            if (current && current.id === widget.id) {
              updateVisualizationOptions(widget.id, {
                gridSpan: current.span,
                ...(current.heightPx != null ? { gridHeightPx: current.heightPx } : {}),
              });
            }
            return null;
          });
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      },
    [updateVisualizationOptions],
  );

  const resizeHandle = (
    widget: WidgetConfig,
    startSpan: number,
    startHeightPx: number | undefined,
    resizeHeight: boolean,
    minHeightPx: number = CHART_MIN_HEIGHT_PX,
    maxHeightPx: number = CHART_MAX_HEIGHT_PX,
  ) =>
    editingLayout && (
      <div
        draggable={false}
        onDragStart={(event) => event.stopPropagation()}
        onMouseDown={startResize(widget, startSpan, startHeightPx, resizeHeight, minHeightPx, maxHeightPx)}
        title="Drag to resize"
        className={cn(
          "absolute bottom-1 right-1 z-10 rounded-sm border border-line-secondary bg-bg-primary opacity-70 hover:opacity-100",
          resizeHeight ? "h-3.5 w-3.5 cursor-nwse-resize" : "h-4 w-2 cursor-ew-resize",
        )}
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

      {editingLayout && (
        <div className="mt-3 rounded-md border border-dashed border-brand-200 bg-brand-50/40 px-3 py-2 text-xs text-ink-secondary">
          Drag any card or chart into any grid position. Drag the handle in a card&apos;s corner to resize it.
        </div>
      )}

      {orderedWidgets.length > 0 && (
        <div
          ref={gridRef}
          className={`${styles.kpiGrid} ${denseGridStyles.denseGrid} mt-3`}
          onDragOver={(event) => { if (editingLayout) event.preventDefault(); }}
          onDrop={handleContainerDrop}
        >
          {orderedWidgets.map((widget) => {
            const preview = resizePreview?.id === widget.id ? resizePreview : null;

            if (widget.type === "kpi") {
              const span = preview?.span ?? widget.visualizationOptions?.gridSpan ?? defaultSpan(widget, 0);
              const kpiHeightPx =
                preview?.heightPx ?? widget.visualizationOptions?.gridHeightPx ?? KPI_HEIGHT_PX;
              return (
                <div
                  key={widget.id}
                  style={{ gridColumn: `span ${span}`, gridRow: `span ${rowSpanFor(kpiHeightPx)}` }}
                  {...dragProps(widget.id)}
                >
                  <Card
                    className={cn(
                      "relative flex h-full flex-col overflow-hidden p-3",
                      editingLayout && "cursor-grab border-dashed",
                    )}
                  >
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
                    <div className="min-h-0 flex-1">
                      <WidgetRenderer
                        widget={widget}
                        data={widgetData[widget.id] ?? []}
                        operational
                        onElementClick={(event) => onElementClick(widget, event)}
                      />
                    </div>
                    {resizeHandle(widget, span, kpiHeightPx, true, KPI_MIN_HEIGHT_PX, KPI_MAX_HEIGHT_PX)}
                  </Card>
                </div>
              );
            }

            const chartIndex = chartIndexById.get(widget.id) ?? 0;
            const span = preview?.span ?? widget.visualizationOptions?.gridSpan ?? defaultSpan(widget, chartIndex);
            const heightPx =
              preview?.heightPx ?? widget.visualizationOptions?.gridHeightPx ?? defaultHeightPx(chartIndex);
            return (
              <div
                key={widget.id}
                style={{ gridColumn: `span ${span}`, gridRow: `span ${rowSpanFor(heightPx)}` }}
                {...dragProps(widget.id)}
              >
                <Card
                  className={cn(
                    "relative flex h-full flex-col overflow-hidden p-3",
                    editingLayout && "cursor-grab border-dashed",
                  )}
                >
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
                  <div className="min-h-0 flex-1">
                    <OperationalWidgetChart
                      widget={widget}
                      rows={widgetData[widget.id] ?? []}
                      className="h-full"
                      onElementClick={onElementClick}
                    />
                  </div>
                  {resizeHandle(widget, span, heightPx, true)}
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
