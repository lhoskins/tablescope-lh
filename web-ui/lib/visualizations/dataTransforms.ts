/**
 * Pure data-shaping helpers used by chart renderers. Kept free of React and
 * Recharts so they can be unit-tested in isolation.
 */

export type Row = Record<string, unknown>;

/** Coerces a value to a finite number, or null when it isn't numeric. */
export function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value.replace(/[,$%]/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Collapses pie/donut categories beyond `maxSlices` into a single "Other"
 * slice (sorted by value descending). When `groupSmallSlices` is false the
 * rows are returned unchanged.
 */
export function preparePieData(
  rows: Row[],
  opts: { nameKey: string; valueKey: string; maxSlices?: number; groupSmallSlices?: boolean }
): Row[] {
  const { nameKey, valueKey, maxSlices = 7, groupSmallSlices = true } = opts;
  if (rows.length === 0) return rows;

  const normalized = rows.map((r) => ({ ...r, [valueKey]: toNumber(r[valueKey]) ?? 0 }));
  if (!groupSmallSlices || normalized.length <= maxSlices) return normalized;

  const sorted = [...normalized].sort(
    (a, b) => (toNumber(b[valueKey]) ?? 0) - (toNumber(a[valueKey]) ?? 0)
  );
  const top = sorted.slice(0, maxSlices - 1);
  const rest = sorted.slice(maxSlices - 1);
  const otherTotal = rest.reduce((sum, r) => sum + (toNumber(r[valueKey]) ?? 0), 0);
  return [...top, { [nameKey]: "Other", [valueKey]: otherTotal }];
}

/**
 * Converts stacked series values into 0..100 percentages per x-row.
 * Used for "100% stacked" bar/area charts.
 */
export function toPercentStacked(rows: Row[], xKey: string, seriesNames: string[]): Row[] {
  return rows.map((row) => {
    const total = seriesNames.reduce((sum, s) => sum + (toNumber(row[s]) ?? 0), 0);
    const out: Row = { [xKey]: row[xKey] };
    for (const s of seriesNames) {
      const v = toNumber(row[s]) ?? 0;
      out[s] = total > 0 ? (v / total) * 100 : 0;
    }
    return out;
  });
}

/** Returns true when every non-empty value in the column parses as a number. */
export function isNumericColumn(rows: Row[], key: string): boolean {
  let seen = false;
  for (const row of rows) {
    const v = row[key];
    if (v === null || v === undefined || v === "") continue;
    seen = true;
    if (toNumber(v) === null) return false;
  }
  return seen;
}
