import type { LayoutItem } from "react-grid-layout";
import { noCompactor, type Compactor } from "react-grid-layout/core";
import type { WidgetConfig } from "@/components/dashboard/types";

export const OPERATIONAL_IMPROVEMENTS_LAYOUT_ID = "operational:improvement-opportunities";

/**
 * Operational dashboards are intentionally free-positioned. No compaction
 * preserves empty rows and columns; collision prevention blocks a dragged or
 * resized widget instead of pushing its neighbours out of place.
 */
export const OPERATIONAL_FREE_POSITION_COMPACTOR: Compactor = {
  ...noCompactor,
  preventCollision: true,
};

export function isHorizontalBar(widget: WidgetConfig): boolean {
  return widget.type === "bar" && (
    widget.visualizationOptions?.barLayout === "horizontal"
    || ["horizontal_bar", "stacked_horizontal", "population_pyramid"].includes(widget.chartSubtype ?? "")
  );
}

function generatedPlacement(widget: WidgetConfig, index: number, kpiCount: number): LayoutItem {
  if (widget.type === "kpi") {
    const width = kpiCount <= 2 ? 6 : kpiCount === 3 ? 4 : 3;
    return { i: widget.id, x: (index % Math.max(1, Math.floor(12 / width))) * width, y: 0, w: width, h: 2, minW: 2, minH: 2 };
  }

  const chartIndex = index - kpiCount;
  if (chartIndex === 0) return { i: widget.id, x: 0, y: 2, w: 6, h: 6, minW: 3, minH: 3, maxW: isHorizontalBar(widget) ? 6 : undefined };
  if (chartIndex === 1) return { i: widget.id, x: 6, y: 2, w: 6, h: 3, minW: 3, minH: 3, maxW: isHorizontalBar(widget) ? 6 : undefined };
  if (chartIndex === 2) return { i: widget.id, x: 6, y: 5, w: 3, h: 3, minW: 3, minH: 3, maxW: isHorizontalBar(widget) ? 6 : undefined };

  const tail = chartIndex - 3;
  return {
    i: widget.id,
    x: (tail % 2) * 6,
    y: 8 + Math.floor(tail / 2) * 4,
    w: 6,
    h: 4,
    minW: 3,
    minH: 3,
    maxW: isHorizontalBar(widget) ? 6 : undefined,
  };
}

/**
 * Produces the ITSM visual hierarchy for AI dashboards while preserving any
 * layout the user has explicitly saved. Horizontal rankings are capped at
 * half width so long category labels remain readable.
 */
export function operationalLayout(
  widgets: WidgetConfig[],
  improvements?: { gridX?: number; gridY?: number; gridW?: number; gridH?: number },
  respectSavedLayout = true,
): LayoutItem[] {
  const ordered = [...widgets].sort((a, b) => (a.type === "kpi" ? -1 : 1) - (b.type === "kpi" ? -1 : 1) || (a.position ?? 0) - (b.position ?? 0));
  const kpiCount = ordered.filter((widget) => widget.type === "kpi").length;
  const items = ordered.map((widget, index) => {
    const fallback = generatedPlacement(widget, index, kpiCount);
    const horizontal = isHorizontalBar(widget);
    return {
      ...fallback,
      x: respectSavedLayout ? widget.gridX ?? fallback.x : fallback.x,
      y: respectSavedLayout ? widget.gridY ?? fallback.y : fallback.y,
      w: Math.min(respectSavedLayout ? widget.gridW ?? fallback.w : fallback.w, horizontal ? 6 : 12),
      h: respectSavedLayout ? widget.gridH ?? fallback.h : fallback.h,
      maxW: horizontal ? 6 : undefined,
    };
  });
  const bottom = items.reduce((value, item) => Math.max(value, item.y + item.h), 0);
  items.push({
    i: OPERATIONAL_IMPROVEMENTS_LAYOUT_ID,
    x: respectSavedLayout ? improvements?.gridX ?? 9 : 9,
    y: respectSavedLayout ? improvements?.gridY ?? Math.max(5, bottom - 3) : Math.max(5, bottom - 3),
    w: Math.min(respectSavedLayout ? improvements?.gridW ?? 3 : 3, 6),
    h: respectSavedLayout ? improvements?.gridH ?? 3 : 3,
    minW: 3,
    minH: 3,
    maxW: 6,
  });
  return items;
}
