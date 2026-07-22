/**
 * Pure data-shaping helpers used by ECharts-based chart renderers. Kept free
 * of React and charting libraries so they can be unit-tested in isolation.
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
 * Builds an ECharts treemap data array from rows: one leaf per row using
 * `nameKey` for the label and `valueKey` for the area. Non-positive values are
 * dropped (treemap requires positive sizes).
 */
export type TreemapNode = { name: string; size?: number; children?: TreemapNode[] };

export function prepareTreemapData(
  rows: Row[],
  opts: { nameKey: string; valueKey: string; groupKey?: string }
): TreemapNode[] {
  const { nameKey, valueKey, groupKey } = opts;
  if (!groupKey) {
    return rows
      .map((r) => ({ name: String(r[nameKey] ?? ""), size: toNumber(r[valueKey]) ?? 0 }))
      .filter((d) => (d.size ?? 0) > 0);
  }
  const groups = new Map<string, TreemapNode[]>();
  for (const r of rows) {
    const size = toNumber(r[valueKey]) ?? 0;
    if (size <= 0) continue;
    const group = String(r[groupKey] ?? "Other");
    const child = { name: String(r[nameKey] ?? ""), size };
    const existing = groups.get(group);
    if (existing) existing.push(child);
    else groups.set(group, [child]);
  }
  return [...groups.entries()].map(([name, children]) => ({ name, children }));
}

/**
 * Builds waterfall segments: each row gets an invisible `base` (the running
 * total before it) and a visible `delta`. The renderer stacks base (transparent)
 * under delta so bars float to show the cumulative running total.
 */
export function prepareWaterfallData(
  rows: Row[],
  opts: { nameKey: string; valueKey: string }
): Array<{ name: string; base: number; delta: number; value: number; cumulative: number }> {
  const { nameKey, valueKey } = opts;
  let running = 0;
  return rows.map((r) => {
    const delta = toNumber(r[valueKey]) ?? 0;
    const base = delta >= 0 ? running : running + delta;
    running += delta;
    return { name: String(r[nameKey] ?? ""), base, delta: Math.abs(delta), value: delta, cumulative: running };
  });
}

/**
 * Ordinary-least-squares line for scatter points. Returns slope/intercept and
 * the two endpoints spanning the x range, or null when a line can't be fit.
 */
export function linearRegression(
  rows: Row[],
  opts: { xKey: string; yKey: string }
): { slope: number; intercept: number; p1: { x: number; y: number }; p2: { x: number; y: number } } | null {
  const { xKey, yKey } = opts;
  const pts = rows
    .map((r) => ({ x: toNumber(r[xKey]), y: toNumber(r[yKey]) }))
    .filter((p): p is { x: number; y: number } => p.x !== null && p.y !== null);
  if (pts.length < 2) return null;
  const n = pts.length;
  const sumX = pts.reduce((s, p) => s + p.x, 0);
  const sumY = pts.reduce((s, p) => s + p.y, 0);
  const sumXY = pts.reduce((s, p) => s + p.x * p.y, 0);
  const sumXX = pts.reduce((s, p) => s + p.x * p.x, 0);
  const denom = n * sumXX - sumX * sumX;
  if (denom === 0) return null;
  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;
  const xs = pts.map((p) => p.x);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  return {
    slope,
    intercept,
    p1: { x: minX, y: slope * minX + intercept },
    p2: { x: maxX, y: slope * maxX + intercept },
  };
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
 * Builds ECharts Sankey {nodes, links} from flat rows of
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
