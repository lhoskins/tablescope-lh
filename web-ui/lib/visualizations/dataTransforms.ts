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

/**
 * Builds a flat Recharts treemap hierarchy from rows: one leaf per row using
 * `nameKey` for the label and `valueKey` for the area. Non-positive values are
 * dropped (treemap requires positive sizes).
 */
export function prepareTreemapData(
  rows: Row[],
  opts: { nameKey: string; valueKey: string }
): Array<{ name: string; size: number }> {
  const { nameKey, valueKey } = opts;
  return rows
    .map((r) => ({ name: String(r[nameKey] ?? ""), size: toNumber(r[valueKey]) ?? 0 }))
    .filter((d) => d.size > 0);
}

/**
 * Shapes rows into funnel segments (name + value), sorted descending so the
 * funnel narrows from top to bottom.
 */
export function prepareFunnelData(
  rows: Row[],
  opts: { nameKey: string; valueKey: string }
): Array<{ name: string; value: number }> {
  const { nameKey, valueKey } = opts;
  return rows
    .map((r) => ({ name: String(r[nameKey] ?? ""), value: toNumber(r[valueKey]) ?? 0 }))
    .filter((d) => d.value > 0)
    .sort((a, b) => b.value - a.value);
}

/**
 * Pivots long rows (subject, series, value) into one record per subject with a
 * column per series — the shape RadarChart expects. When `seriesKey` is unset
 * a single series named by `valueKey` is produced.
 */
export function prepareRadarData(
  rows: Row[],
  opts: { subjectKey: string; valueKey: string; seriesKey?: string }
): { data: Row[]; series: string[] } {
  const { subjectKey, valueKey, seriesKey } = opts;
  const bySubject = new Map<string, Row>();
  const series = new Set<string>();
  for (const r of rows) {
    const subject = String(r[subjectKey] ?? "");
    const seriesName = seriesKey ? String(r[seriesKey] ?? valueKey) : valueKey;
    series.add(seriesName);
    const existing = bySubject.get(subject) ?? { [subjectKey]: subject };
    existing[seriesName] = toNumber(r[valueKey]) ?? 0;
    bySubject.set(subject, existing);
  }
  return { data: [...bySubject.values()], series: [...series] };
}

export type SankeyGraph = {
  nodes: Array<{ name: string }>;
  links: Array<{ source: number; target: number; value: number }>;
};

/**
 * Builds Recharts Sankey {nodes, links} from flat rows of
 * (source, target, value). Source and target names share one node index space;
 * identical (source,target) pairs are summed.
 */
export function prepareSankeyData(
  rows: Row[],
  opts: { sourceKey: string; targetKey: string; valueKey: string }
): SankeyGraph {
  const { sourceKey, targetKey, valueKey } = opts;
  const index = new Map<string, number>();
  const nodes: Array<{ name: string }> = [];
  const idFor = (name: string): number => {
    const existing = index.get(name);
    if (existing !== undefined) return existing;
    const id = nodes.length;
    index.set(name, id);
    nodes.push({ name });
    return id;
  };

  const linkTotals = new Map<string, number>();
  for (const r of rows) {
    const source = String(r[sourceKey] ?? "");
    const target = String(r[targetKey] ?? "");
    const value = toNumber(r[valueKey]) ?? 0;
    if (!source || !target || value <= 0) continue;
    const key = `${source}\u0000${target}`;
    linkTotals.set(key, (linkTotals.get(key) ?? 0) + value);
  }

  const links: SankeyGraph["links"] = [];
  for (const [key, value] of linkTotals) {
    const [source, target] = key.split("\u0000");
    links.push({ source: idFor(source), target: idFor(target), value });
  }
  return { nodes, links };
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
