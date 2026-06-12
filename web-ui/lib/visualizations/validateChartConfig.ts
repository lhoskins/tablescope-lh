/**
 * Lightweight chart-config validation. Surfaces friendly setup messages and
 * lets the renderer fall back to a table when a chart can't be drawn.
 */

import type { WidgetConfig } from "@/components/dashboard/types";
import { getChartDefinition } from "./chartRegistry";
import { isNumericColumn, type Row } from "./dataTransforms";

export interface ChartValidationResult {
  ok: boolean;
  /** Hard errors that should block chart rendering (fall back to table). */
  errors: string[];
  /** Non-blocking advisories (e.g. too many pie slices). */
  warnings: string[];
}

export function validateChartConfig(widget: WidgetConfig, rows: Row[] = []): ChartValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  const def = getChartDefinition(widget.type);
  if (!def) {
    return { ok: false, errors: [`Unknown chart type "${widget.type}".`], warnings };
  }

  // Required field presence.
  if (def.requiredFields.includes("x") && !widget.xColumn && !widget.xKey) {
    errors.push("This chart needs a category or X-axis field.");
  }
  if (def.requiredFields.includes("y") && !widget.yColumn && !widget.yKey) {
    errors.push("This chart needs a numeric value field.");
  }

  // Data-aware checks (only when we actually have rows).
  if (rows.length > 0) {
    const yKey = widget.yColumn || widget.yKey || "";
    if (def.requiredFields.includes("y") && yKey && !isNumericColumn(rows, yKey)) {
      // Aggregated queries rename the value column (sum_/avg_/...), so only warn.
      const hasAggCol = Object.keys(rows[0]).some((k) =>
        ["sum_", "avg_", "count_", "min_", "max_"].some((p) => k.startsWith(p))
      );
      if (!hasAggCol) warnings.push("The selected value field is not numeric.");
    }

    if (widget.type === "pie") {
      const max = widget.visualizationOptions?.maxSlices ?? 7;
      const group = widget.visualizationOptions?.groupSmallSlices ?? true;
      if (!group && rows.length > max) {
        warnings.push("Pie charts work best with 7 or fewer categories. Enable grouping small slices.");
      }
    }

    if (widget.visualizationOptions?.dualAxis) {
      const hasGroup = !!widget.groupByColumn;
      const hasY2 = !!widget.y2Column;
      if (!hasGroup && !hasY2) {
        warnings.push("Dual axis needs at least two series (add a Group By or secondary Y).");
      }
    }

    if (widget.type === "sankey") {
      const target = widget.visualizationOptions?.targetColumn || widget.groupByColumn;
      if (!target) {
        warnings.push("Sankey charts need source (X), target (Group By), and value (Y) fields.");
      }
    }

    if (widget.type === "scatter") {
      const xKey = widget.xColumn || widget.xKey || "";
      if (xKey && !isNumericColumn(rows, xKey)) {
        warnings.push("Scatter charts work best when the X axis is numeric.");
      }
      if ((widget.visualizationOptions?.bubble || widget.chartSubtype === "bubble") && !widget.visualizationOptions?.zColumn && !widget.y2Column) {
        warnings.push("Bubble charts need a Z (size) field — set the secondary Y.");
      }
    }
  }

  return { ok: errors.length === 0, errors, warnings };
}
