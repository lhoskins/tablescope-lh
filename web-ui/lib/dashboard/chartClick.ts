/**
 * Normalize Recharts click events into a single `ChartClickEvent` shape
 * ({ sourceField, value, label }) regardless of chart family.
 *
 * Cartesian charts (bar/line/area/combo) fire a chart-level `onClick` whose
 * state carries `activeLabel` — the clicked category on the X axis. Pie charts
 * fire `onClick` on the slice with the slice payload, so the clicked value is
 * the slice's name-key field.
 */

import type { ChartClickEvent } from "@/components/dashboard/types";

function humanize(field: string): string {
  return field.replace(/[_]+/g, " ").trim();
}

function buildLabel(sourceField: string, value: string | number): string {
  return `${humanize(sourceField)}: ${value}`;
}

/** Minimal shape of the categorical chart state Recharts passes to onClick. */
export type CartesianClickState = {
  activeLabel?: string | number;
  activePayload?: Array<{ payload?: Record<string, unknown> }>;
} | null;

/**
 * Normalize a cartesian (bar/line/area/combo) chart click.
 * Returns null when nothing actionable was clicked.
 */
export function normalizeCartesianClick(
  state: CartesianClickState,
  sourceField: string,
): ChartClickEvent | null {
  if (!state || state.activeLabel === undefined || state.activeLabel === null) {
    return null;
  }
  const value = state.activeLabel;
  if (typeof value !== "string" && typeof value !== "number") return null;
  return { sourceField, value, label: buildLabel(sourceField, value) };
}

/**
 * Normalize a pie/donut slice click. `nameKey` is the slice's category field.
 * Recharts passes the slice payload (the data row) as the first argument.
 */
export function normalizePieClick(
  entry: Record<string, unknown> | null | undefined,
  sourceField: string,
  nameKey: string,
): ChartClickEvent | null {
  if (!entry) return null;
  const raw = entry[nameKey] ?? entry.name;
  if (typeof raw !== "string" && typeof raw !== "number") return null;
  return { sourceField, value: raw, label: buildLabel(sourceField, raw) };
}
