/**
 * Translate ephemeral dashboard runtime state (date range + cross-filters)
 * into per-widget `WidgetFilter`s, applying compatibility rules so widgets
 * that don't carry the filtered field are left untouched.
 */

import type {
  CrossFilter,
  DashboardDateRange,
  DashboardRuntimeState,
  WidgetConfig,
  WidgetFilter,
} from "@/components/dashboard/types";

/** Case-insensitive membership test against a widget's known column names. */
export function isFieldCompatible(field: string, columns: string[]): boolean {
  if (!field) return false;
  const target = field.toLowerCase();
  return columns.some((c) => c.toLowerCase() === target);
}

export function crossFilterToWidgetFilter(cf: CrossFilter): WidgetFilter {
  return { column: cf.sourceField, operator: "eq", value: cf.value };
}

export function dateRangeToWidgetFilters(
  field: string,
  range: DashboardDateRange,
): WidgetFilter[] {
  const out: WidgetFilter[] = [];
  if (range.start) out.push({ column: field, operator: "gte", value: range.start });
  if (range.end) out.push({ column: field, operator: "lte", value: range.end });
  return out;
}

/**
 * Build the runtime filters that apply to a single widget.
 *
 * - Cross-filters apply when the widget exposes the source field and the
 *   widget is NOT the one that originated the filter (so a chart never
 *   collapses itself to the clicked value).
 * - The date range applies when the widget has an enabled date field that is
 *   present in its columns.
 *
 * `columns` is the widget's known column set (its view/query schema). When the
 * column set is unknown (empty), we fall back to the widget's configured
 * x/group/date columns so cross-filtering still works on the common case.
 */
export function buildRuntimeWidgetFilters(
  widget: WidgetConfig,
  runtime: DashboardRuntimeState,
  columns: string[],
): WidgetFilter[] {
  const known = columns.length > 0
    ? columns
    : [widget.xColumn, widget.yColumn, widget.groupByColumn, widget.dateField?.field].filter(
        (c): c is string => !!c,
      );

  const out: WidgetFilter[] = [];

  for (const cf of runtime.crossFilters) {
    if (cf.sourceWidgetId === widget.id) continue;
    if (isFieldCompatible(cf.sourceField, known)) {
      out.push(crossFilterToWidgetFilter(cf));
    }
  }

  if (runtime.dateRange && widget.dateField?.enabled && widget.dateField.field) {
    if (isFieldCompatible(widget.dateField.field, known)) {
      out.push(...dateRangeToWidgetFilters(widget.dateField.field, runtime.dateRange));
    }
  }

  return out;
}
