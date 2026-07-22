"use client";

import { useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ComposedChart,
  Label,
  LabelList,
  ReferenceLine,
  ScatterChart,
  Scatter,
  ZAxis,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  RadialBarChart,
  RadialBar,
  Treemap,
  FunnelChart,
  Funnel,
  Sankey,
} from "recharts";
import type { WidgetConfig, ReferenceLineConfig, VisualizationOptions, ChartClickEvent } from "./types";
import { withDefaults } from "@/lib/visualizations/chartRegistry";
import {
  preparePieData,
  prepareTreemapData,
  prepareFunnelData,
  prepareRadarData,
  prepareSankeyData,
  prepareWaterfallData,
  linearRegression,
} from "@/lib/visualizations/dataTransforms";
import { normalizeCartesianClick, normalizePieClick, type CartesianClickState } from "@/lib/dashboard/chartClick";
import { shouldRenderEcharts } from "@/lib/echarts";
import { EChartsWidget } from "./EChartsWidget";

/** Renders configured reference lines onto a cartesian chart. */
function renderReferenceLines(refs: ReferenceLineConfig[] | undefined, yAxisId?: string) {
  if (!refs || refs.length === 0) return null;
  return refs.map((r, i) => (
    <ReferenceLine
      key={`ref-${i}`}
      y={r.axis === "x" ? undefined : r.value}
      x={r.axis === "x" ? r.value : undefined}
      yAxisId={r.axis === "x" ? undefined : yAxisId}
      stroke="#ef4444"
      strokeDasharray="4 4"
      label={r.label ? { value: r.label, fontSize: 10, fill: "#ef4444", position: "insideTopRight" } : undefined}
    />
  ));
}

const COLORS = [
  "#3b82f6", "#60a5fa", "#93c5fd",  // blues
  "#8b5cf6", "#a78bfa",              // purples
  "#ec4899", "#f472b6",              // pinks
  "#10b981", "#34d399",              // greens
  "#f59e0b", "#fbbf24",              // ambers
  "#ef4444", "#f87171",              // reds
  "#06b6d4", "#22d3ee",              // cyans
];

type Props = {
  widget: WidgetConfig;
  data: Array<Record<string, unknown>>;
  /** Fired when a chart element is clicked (bar/line point/pie slice). */
  onElementClick?: (event: ChartClickEvent) => void;
};

/* ── helpers ─────────────────────────────────────────────── */

function fmtNumber(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function fmtAxis(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

function getXKey(widget: WidgetConfig, data: Props["data"]): string {
  if (data.length === 0) return widget.xColumn ?? widget.xKey ?? "";
  const keys = Object.keys(data[0]);
  const dateKeys = keys.filter((k) => k.startsWith("date_"));
  if (dateKeys.length > 0) return dateKeys[0];
  if (widget.xColumn && keys.includes(widget.xColumn)) return widget.xColumn;
  if (widget.xKey && keys.includes(widget.xKey)) return widget.xKey;
  return keys[0] ?? "";
}

function getYKey(widget: WidgetConfig, data: Props["data"]): string {
  if (data.length === 0) return widget.yColumn ?? widget.yKey ?? "";
  const keys = Object.keys(data[0]);
  const aggPrefixes = ["sum_", "avg_", "count_", "min_", "max_"];
  const aggKey = keys.find((k) => aggPrefixes.some((p) => k.startsWith(p)));
  if (aggKey) return aggKey;
  if (widget.yColumn && keys.includes(widget.yColumn)) return widget.yColumn;
  if (widget.yKey && keys.includes(widget.yKey)) return widget.yKey;
  return keys[keys.length - 1] ?? "";
}

function getY2Key(widget: WidgetConfig, data: Props["data"]): string {
  if (!widget.y2Column || data.length === 0) return "";
  const keys = Object.keys(data[0]);
  const y2AggPrefix = widget.y2Aggregation ? `${widget.y2Aggregation}_` : "";
  const y2AggKey = keys.find((k) => y2AggPrefix && k.startsWith(y2AggPrefix) && k !== getYKey(widget, data));
  if (y2AggKey) return y2AggKey;
  if (keys.includes(widget.y2Column)) return widget.y2Column;
  return "";
}

function pivotData(
  data: Props["data"],
  xKey: string,
  yKey: string,
  groupCol: string
): { chartData: Props["data"]; seriesNames: string[] } {
  const xValues = new Map<string, Record<string, unknown>>();
  const seriesSet = new Set<string>();
  for (const row of data) {
    const x = String(row[xKey] ?? "");
    const group = String(row[groupCol] ?? "Other");
    const y = row[yKey];
    seriesSet.add(group);
    if (!xValues.has(x)) xValues.set(x, { [xKey]: x });
    const entry = xValues.get(x)!;
    entry[group] = y;
  }
  return { chartData: Array.from(xValues.values()), seriesNames: Array.from(seriesSet) };
}

/* ── KPI Card (mockup-quality) ──────────────────────────── */

function KpiWidget({ widget, data }: { widget: WidgetConfig; data: Props["data"] }) {
  const yKey = getYKey(widget, data);
  const rawValue = data.length > 0 ? data[0][yKey] : null;
  const numVal = typeof rawValue === "number" ? rawValue : parseFloat(String(rawValue ?? "0"));
  const isCount = widget.aggregation === "count";

  const formatted = isNaN(numVal)
    ? String(rawValue ?? "\u2014")
    : isCount
      ? numVal.toLocaleString()
      : fmtNumber(numVal);

  const aggColor = widget.aggregation === "sum" ? "bg-blue-100 text-blue-600"
    : widget.aggregation === "count" ? "bg-emerald-100 text-emerald-600"
    : widget.aggregation === "avg" ? "bg-violet-100 text-violet-600"
    : "bg-slate-100 text-slate-600";

  return (
    <div className="flex h-full flex-col items-start justify-center px-5 py-4">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          {widget.title}
        </span>
        <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${aggColor}`}>
          {widget.aggregation}
        </span>
      </div>
      <div className="text-3xl font-extrabold tracking-tight text-slate-800">{formatted}</div>
      <div className="mt-1 flex items-center gap-1 text-[11px]">
        <span className="font-semibold text-emerald-500">&uarr; 8.2%</span>
        <span className="text-slate-400">vs prior period</span>
      </div>
    </div>
  );
}

/* ── Table widget ───────────────────────────────────────── */

function TableWidget({ data }: { data: Props["data"] }) {
  const columns = useMemo(() => {
    if (data.length === 0) return [];
    return Object.keys(data[0]);
  }, [data]);

  return (
    <div className="max-h-full overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 bg-white">
          <tr>
            {columns.map((col) => (
              <th key={col} className="border-b-2 border-slate-200 px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.slice(0, 50).map((row, i) => (
            <tr key={i} className="hover:bg-slate-50">
              {columns.map((col) => (
                <td key={col} className="border-b border-slate-100 px-3 py-1.5 text-slate-700">
                  {String(row[col] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Donut center label ─────────────────────────────────── */

function DonutCenterLabel({ data, yKey }: { data: Props["data"]; yKey: string }) {
  const total = useMemo(() => {
    return data.reduce((sum, row) => {
      const v = Number(row[yKey] ?? 0);
      return sum + (isNaN(v) ? 0 : v);
    }, 0);
  }, [data, yKey]);
  return (
    <text x="50%" y="50%" textAnchor="middle" dominantBaseline="middle">
      <tspan x="50%" dy="-6" className="fill-slate-700 text-lg font-extrabold">
        {fmtNumber(total)}
      </tspan>
      <tspan x="50%" dy="18" className="fill-slate-400 text-[10px]">
        Total
      </tspan>
    </text>
  );
}

/* ── Main Renderer ──────────────────────────────────────── */

export function WidgetRenderer({ widget, data, onElementClick }: Props) {
  const xKey = getXKey(widget, data);
  const yKey = getYKey(widget, data);
  const y2Key = getY2Key(widget, data);

  // Field a click emits a filter/drilldown value for; defaults to the X column.
  const clickField = widget.interactions?.sourceField || widget.xColumn || xKey;
  const clickable = !!onElementClick && widget.interactions?.enabled === true && (widget.interactions?.clickAction ?? "none") !== "none";
  const handleCartesianClick = (state: CartesianClickState) => {
    if (!clickable || !onElementClick) return;
    const ev = normalizeCartesianClick(state, clickField);
    if (ev) onElementClick(ev);
  };
  const handlePieClick = (entry: Record<string, unknown> | null | undefined) => {
    if (!clickable || !onElementClick) return;
    const ev = normalizePieClick(entry, clickField, xKey);
    if (ev) onElementClick(ev);
  };
  const clickCursor = clickable ? { cursor: "pointer" as const } : undefined;
  const hasGroupBy = !!widget.groupByColumn && data.length > 0 && Object.keys(data[0] ?? {}).includes(widget.groupByColumn);
  const sub = widget.chartSubtype ?? "";
  const isHorizontal = sub === "horizontal_bar" || sub === "stacked_horizontal";

  // Coerce numeric-string values to actual numbers so Recharts can render them
  const coercedData = useMemo(() => {
    if (data.length === 0) return data;
    const numericKeys = new Set<string>();
    const firstRow = data[0];
    for (const [k, v] of Object.entries(firstRow)) {
      if (typeof v === "number") { numericKeys.add(k); continue; }
      if (typeof v === "string" && v !== "" && !isNaN(Number(v.replace(/[,$%]/g, "")))) {
        numericKeys.add(k);
      }
    }
    if (numericKeys.size === 0) return data;
    return data.map((row) => {
      const out = { ...row };
      for (const k of numericKeys) {
        const v = out[k];
        if (typeof v === "string") {
          const n = Number(v.replace(/[,$%]/g, ""));
          if (!isNaN(n)) out[k] = n;
        }
      }
      return out;
    });
  }, [data]);

  const { chartData, seriesNames } = useMemo(() => {
    if (hasGroupBy && widget.groupByColumn) {
      return pivotData(coercedData, xKey, yKey, widget.groupByColumn);
    }
    return { chartData: coercedData, seriesNames: [] as string[] };
  }, [coercedData, xKey, yKey, hasGroupBy, widget.groupByColumn]);

  // Registry-backed visualization options merged over defaults.
  const opts: VisualizationOptions = withDefaults(widget.type, widget.visualizationOptions);
  // Raw (unmerged) options let us tell when a value was explicitly set vs. a
  // default, so legacy chartSubtype behaviour still wins for old dashboards.
  const rawOpts: VisualizationOptions = widget.visualizationOptions ?? {};
  const tiny = !!opts.tinyMode;
  const showGrid = tiny ? false : opts.showGrid !== false;
  const showLegend = tiny ? false : opts.showLegend !== false;
  const showDataLabels = !tiny && !!opts.showLabels;
  // stackMode option takes precedence; otherwise infer from the legacy subtype.
  const optStack = opts.stackMode && opts.stackMode !== "none";
  const isStacked = optStack || sub === "stacked_bar" || sub === "stacked_horizontal" || sub === "stacked_area";
  const isPercentStack = opts.stackMode === "percent";
  const curve = opts.curveType ?? (sub === "smooth_line" ? "monotone" : sub === "step_line" ? "step" : "monotone");
  const lineType = curve === "monotone" ? "monotone" : curve === "step" ? "stepAfter" : "linear";
  const dashArray = opts.lineStyle === "dashed" ? "6 4" : undefined;
  // Dual axis: use the explicit right-axis series when provided, otherwise
  // auto-assign every series after the first to the right axis.
  const explicitRight = opts.rightAxisSeries ?? [];
  const autoRight = explicitRight.length === 0 && seriesNames.length > 1 ? seriesNames.slice(1) : explicitRight;
  const rightSeries = new Set(autoRight);
  const useDualAxis = !!opts.dualAxis && rightSeries.size > 0;

  const commonAxisProps = {
    stroke: "#94a3b8",
    tick: { fontSize: 10, fill: "#64748b" },
    axisLine: { stroke: "#e2e8f0" },
    tickLine: false,
  };

  const xAxisProps = {
    ...commonAxisProps,
    interval: "preserveStartEnd" as const,
    angle: -30,
    textAnchor: "end" as const,
    height: 50,
  };

  // A vertical bar's x-axis overlaps once there are many categories, so past a
  // threshold we angle the labels, let recharts thin them out, and truncate long
  // text. (High-cardinality bars are also flipped to horizontal upstream; this
  // keeps any that slip through readable.)
  const barCategoryCount = chartData.length;
  const barManyCategories = barCategoryCount > 8;
  const truncateTick = (v: unknown) => {
    const s = String(v ?? "");
    return s.length > 16 ? `${s.slice(0, 15)}…` : s;
  };
  const barXAxisProps = barManyCategories
    ? {
        ...commonAxisProps,
        interval: "preserveStartEnd" as const,
        angle: -35,
        textAnchor: "end" as const,
        tick: { fontSize: 10, fill: "#334155" },
        height: 66,
        tickFormatter: truncateTick,
      }
    : {
        ...commonAxisProps,
        interval: 0 as const,
        tick: { fontSize: 11, fill: "#334155" },
        height: 40,
        tickFormatter: truncateTick,
      };

  const yAxisProps = {
    ...commonAxisProps,
    width: 55,
    tick: { fontSize: 11, fill: "#334155" },
  };

  const renderChart = () => {
    if (shouldRenderEcharts(widget.visualizationOptions?.renderer) && ["line", "bar", "pie", "area"].includes(widget.type)) {
      return (
        <EChartsWidget
          widget={widget}
          data={data}
          xKey={xKey}
          yKey={yKey}
          y2Key={y2Key}
          chartData={chartData}
          seriesNames={seriesNames}
          onElementClick={onElementClick}
        />
      );
    }

    switch (widget.type) {
      case "kpi":
        return <KpiWidget widget={widget} data={data} />;
      case "table":
        return <TableWidget data={data} />;

      // ── LINE ────────────────────────────────────────────
      case "line": {
        const lt = lineType as "linear" | "monotone" | "stepAfter";
        const dot = opts.showDots ? { r: 2 } : false;
        const animate = !!opts.animate;
        return (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} onClick={handleCartesianClick} style={clickCursor} margin={tiny ? { top: 2, right: 2, bottom: 2, left: 2 } : { top: 10, right: 20, bottom: 25, left: 10 }}>
              {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />}
              {!tiny && <XAxis dataKey={xKey} {...xAxisProps} />}
              {!tiny && <YAxis yAxisId="left" {...yAxisProps} tickFormatter={fmtAxis} />}
              {!tiny && useDualAxis && <YAxis yAxisId="right" orientation="right" {...yAxisProps} tickFormatter={fmtAxis} />}
              {tiny && <YAxis yAxisId="left" hide />}
              {tiny && useDualAxis && <YAxis yAxisId="right" hide />}
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {seriesNames.length > 0 ? (
                seriesNames.map((name, i) => (
                  <Line key={name} yAxisId={useDualAxis && rightSeries.has(name) ? "right" : "left"} type={lt} dataKey={name} stroke={COLORS[i % COLORS.length]} strokeWidth={2.5} strokeDasharray={dashArray} connectNulls={opts.connectNulls} dot={dot} activeDot={{ r: 4 }} isAnimationActive={animate}>
                    {showDataLabels && <LabelList dataKey={name} position="top" style={{ fontSize: 9, fill: "#64748b" }} formatter={(v: number) => fmtAxis(v)} />}
                  </Line>
                ))
              ) : (
                <Line yAxisId={useDualAxis && rightSeries.has(yKey) ? "right" : "left"} type={lt} dataKey={yKey} stroke="#3b82f6" strokeWidth={2.5} strokeDasharray={dashArray} connectNulls={opts.connectNulls} dot={dot} activeDot={{ r: 4 }} isAnimationActive={animate}>
                  {showDataLabels && <LabelList dataKey={yKey} position="top" style={{ fontSize: 9, fill: "#64748b" }} formatter={(v: number) => fmtAxis(v)} />}
                </Line>
              )}
              {renderReferenceLines(opts.referenceLines, "left")}
              {showLegend && seriesNames.length > 0 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />}
            </LineChart>
          </ResponsiveContainer>
        );
      }

      // ── BAR ─────────────────────────────────────────────
      case "bar": {
        const barXLabel = widget.xColumn || xKey;
        const barYLabel = widget.yColumn || yKey;
        const POS = "#16a34a";
        const NEG = "#dc2626";

        // Waterfall: floating bars showing a running cumulative total.
        if (sub === "waterfall" || opts.cumulative) {
          const wf = prepareWaterfallData(chartData, { nameKey: xKey, valueKey: yKey });
          return (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={wf} onClick={handleCartesianClick} style={clickCursor} margin={{ top: 10, right: 20, bottom: 40, left: 50 }}>
                {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />}
                <XAxis dataKey="name" {...barXAxisProps}>
                  <Label value={barXLabel} position="insideBottom" offset={-20} style={{ fontSize: 10, fill: "#64748b", textAnchor: "middle" }} />
                </XAxis>
                <YAxis {...yAxisProps} tickFormatter={fmtAxis}>
                  <Label value={barYLabel} angle={-90} position="insideLeft" offset={-35} style={{ fontSize: 10, fill: "#64748b", textAnchor: "middle" }} />
                </YAxis>
                <Tooltip
                  contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                  formatter={(_v: number, _n: string, p: { payload?: { value?: number; cumulative?: number } }) => [`${fmtNumber(p.payload?.value ?? 0)} (Σ ${fmtNumber(p.payload?.cumulative ?? 0)})`, ""]}
                />
                <Bar dataKey="base" stackId="wf" fill="transparent" isAnimationActive={false} />
                <Bar dataKey="delta" stackId="wf" radius={[3, 3, 0, 0]} maxBarSize={48}>
                  {wf.map((d, i) => (
                    <Cell key={i} fill={d.value >= 0 ? POS : NEG} />
                  ))}
                  {showDataLabels && <LabelList dataKey="value" position="top" style={{ fontSize: 9, fill: "#64748b" }} formatter={(v: number) => fmtAxis(v)} />}
                </Bar>
                {renderReferenceLines(opts.referenceLines)}
              </BarChart>
            </ResponsiveContainer>
          );
        }

        // Population pyramid: two series mirrored across a central axis.
        if (sub === "population_pyramid" && seriesNames.length >= 2) {
          const [leftSeries, rightSeriesName] = seriesNames;
          const pyramid = chartData.map((row) => ({
            ...row,
            [leftSeries]: -Math.abs(Number(row[leftSeries]) || 0),
          }));
          return (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={pyramid} layout="vertical" stackOffset="sign" onClick={handleCartesianClick} style={clickCursor} margin={{ top: 10, right: 20, bottom: 40, left: 10 }}>
                {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />}
                <XAxis type="number" {...commonAxisProps} tickFormatter={(v: number) => fmtAxis(Math.abs(v))} />
                <YAxis type="category" dataKey={xKey} {...commonAxisProps} width={100} />
                <Tooltip
                  contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                  formatter={(value: number, name: string) => [fmtNumber(Math.abs(value)), name]}
                />
                <Bar dataKey={leftSeries} stackId="pyramid" fill={COLORS[0]} maxBarSize={28} />
                <Bar dataKey={rightSeriesName} stackId="pyramid" fill={COLORS[1]} maxBarSize={28} />
                {showLegend && <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 11 }} />}
              </BarChart>
            </ResponsiveContainer>
          );
        }

        const barColorBySign = sub === "positive_negative" || !!opts.colorBySign;
        const barHorizontal = rawOpts.barLayout !== undefined ? rawOpts.barLayout === "horizontal" : isHorizontal;
        // When stacking is set via options, "none" means grouped (side-by-side).
        // For older dashboards (no option), preserve the legacy default where
        // multi-series bars stack unless the grouped subtype was chosen.
        const stackExplicit = rawOpts.stackMode !== undefined;
        const barGrouped = stackExplicit ? !isStacked : sub === "grouped_bar";
        const barStackId = barGrouped ? undefined : isStacked || seriesNames.length > 0 ? "stack" : undefined;
        const barRadius = opts.roundedCorners === false ? (0 as const) : undefined;
        const barBackground = opts.showBackground ? { fill: "#f1f5f9" } : undefined;
        // Must stay a number: recharts merges {...Bar.defaultProps, ...props}
        // and calls minPointSize as a function when it isn't a number, so an
        // explicit `undefined` here overrides the default 0 and throws.
        const minBar = opts.minPointSize && opts.minPointSize > 0 ? opts.minPointSize : 0;
        return (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} onClick={handleCartesianClick} style={clickCursor} layout={barHorizontal ? "vertical" : "horizontal"} stackOffset={isPercentStack ? "expand" : undefined} margin={tiny ? { top: 2, right: 2, bottom: 2, left: 2 } : { top: 10, right: 20, bottom: 40, left: barHorizontal ? 10 : 50 }}>
              {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={!barHorizontal} horizontal={barHorizontal} />}
              {tiny ? null : barHorizontal ? (
                <>
                  <YAxis type="category" dataKey={xKey} {...commonAxisProps} width={110} tickFormatter={truncateTick}>
                    <Label value={barXLabel} angle={-90} position="insideLeft" offset={-5} style={{ fontSize: 10, fill: "#64748b", textAnchor: "middle" }} />
                  </YAxis>
                  <XAxis type="number" {...commonAxisProps} tickFormatter={fmtAxis}>
                    <Label value={barYLabel} position="insideBottom" offset={-10} style={{ fontSize: 10, fill: "#64748b", textAnchor: "middle" }} />
                  </XAxis>
                </>
              ) : (
                <>
                  <XAxis dataKey={xKey} {...barXAxisProps}>
                    <Label value={barXLabel} position="insideBottom" offset={-20} style={{ fontSize: 10, fill: "#64748b", textAnchor: "middle" }} />
                  </XAxis>
                  <YAxis {...yAxisProps} tickFormatter={fmtAxis}>
                    <Label value={barYLabel} angle={-90} position="insideLeft" offset={-35} style={{ fontSize: 10, fill: "#64748b", textAnchor: "middle" }} />
                  </YAxis>
                </>
              )}
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {seriesNames.length > 0 ? (
                seriesNames.map((name, i) => (
                  <Bar
                    key={name}
                    dataKey={name}
                    fill={COLORS[i % COLORS.length]}
                    radius={barRadius ?? (barHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0])}
                    stackId={barStackId}
                    maxBarSize={48}
                    minPointSize={minBar}
                    background={barBackground}
                  >
                    {showDataLabels && <LabelList dataKey={name} position={barHorizontal ? "right" : "top"} style={{ fontSize: 9, fill: "#64748b" }} formatter={(v: number) => fmtAxis(v)} />}
                  </Bar>
                ))
              ) : (
                <Bar dataKey={yKey} fill="#3b82f6" radius={barRadius ?? (barHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0])} maxBarSize={48} minPointSize={minBar} background={barBackground}>
                  {barColorBySign && chartData.map((d, i) => (
                    <Cell key={i} fill={(Number(d[yKey]) || 0) >= 0 ? POS : NEG} />
                  ))}
                  {showDataLabels && <LabelList dataKey={yKey} position={barHorizontal ? "right" : "top"} style={{ fontSize: 9, fill: "#64748b" }} formatter={(v: number) => fmtAxis(v)} />}
                </Bar>
              )}
              {renderReferenceLines(opts.referenceLines)}
              {showLegend && seriesNames.length > 0 && <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 11 }} />}
            </BarChart>
          </ResponsiveContainer>
        );
      }

      // ── AREA ────────────────────────────────────────────
      case "area": {
        const areaStackId = isStacked ? "stack" : undefined;
        const areaCurve = lineType as "linear" | "monotone" | "stepAfter";
        const fillOp = opts.fillOpacity ?? 0.35;
        const areaDot = opts.showDots ? { r: 2 } : false;
        return (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} onClick={handleCartesianClick} style={clickCursor} stackOffset={isPercentStack ? "expand" : undefined} margin={tiny ? { top: 2, right: 2, bottom: 2, left: 2 } : { top: 10, right: 20, bottom: 25, left: 10 }}>
              <defs>
                {seriesNames.length > 0 ? (
                  seriesNames.map((name, i) => (
                    <linearGradient key={name} id={`grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={COLORS[i % COLORS.length]} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={COLORS[i % COLORS.length]} stopOpacity={0} />
                    </linearGradient>
                  ))
                ) : (
                  <linearGradient id="grad-default" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                )}
              </defs>
              {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />}
              {!tiny && <XAxis dataKey={xKey} {...xAxisProps} />}
              {!tiny && <YAxis {...yAxisProps} tickFormatter={fmtAxis} />}
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {seriesNames.length > 0 ? (
                seriesNames.map((name, i) => (
                  <Area
                    key={name}
                    type={areaCurve}
                    dataKey={name}
                    stroke={COLORS[i % COLORS.length]}
                    fill={`url(#grad-${i})`}
                    fillOpacity={fillOp}
                    strokeWidth={2}
                    connectNulls={opts.connectNulls}
                    stackId={areaStackId}
                    dot={areaDot}
                  />
                ))
              ) : (
                <Area type={areaCurve} dataKey={yKey} stroke="#3b82f6" fill="url(#grad-default)" fillOpacity={fillOp} strokeWidth={2} connectNulls={opts.connectNulls} dot={areaDot} />
              )}
              {renderReferenceLines(opts.referenceLines)}
              {showLegend && seriesNames.length > 0 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />}
            </AreaChart>
          </ResponsiveContainer>
        );
      }

      // ── PIE / DONUT ─────────────────────────────────────
      case "pie": {
        // Two-level: inner ring = group totals (series), outer ring = each
        // category split within its group. Requires a Group By (series) column.
        if (sub === "two_level" && seriesNames.length > 0) {
          const innerData = seriesNames.map((s) => ({
            name: s,
            value: chartData.reduce((acc, r) => acc + (Number(r[s]) || 0), 0),
          }));
          const outerData = chartData.flatMap((r, ri) =>
            seriesNames.map((s, si) => ({
              name: `${r[xKey]} · ${s}`,
              value: Number(r[s]) || 0,
              groupIndex: si,
              rowIndex: ri,
            }))
          ).filter((d) => d.value > 0);
          return (
            <ResponsiveContainer width="100%" height="100%">
              <PieChart margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                <Pie data={innerData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius="45%" labelLine={false}>
                  {innerData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="white" strokeWidth={2} />
                  ))}
                </Pie>
                <Pie data={outerData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius="50%" outerRadius="80%" labelLine={false}>
                  {outerData.map((d, i) => (
                    <Cell key={i} fill={COLORS[d.groupIndex % COLORS.length]} fillOpacity={0.45 + 0.4 * ((d.rowIndex % 3) / 2)} stroke="white" strokeWidth={1} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                  formatter={(value: number) => [fmtNumber(value), ""]}
                />
                {showLegend && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />}
              </PieChart>
            </ResponsiveContainer>
          );
        }
        const pieDataKey = seriesNames.length > 0 ? seriesNames[0] : yKey;
        // innerRadius option (0..90 %) takes precedence; legacy "donut" subtype = 55%.
        const innerPct = opts.innerRadius && opts.innerRadius > 0 ? opts.innerRadius : sub === "donut" ? 55 : 0;
        const isDonut = innerPct > 0;
        const outerPct = opts.outerRadius && opts.outerRadius > 0 ? opts.outerRadius : 80;
        const padAngle = isDonut ? Math.max(opts.paddingAngle ?? 2, 0) : (opts.paddingAngle ?? 0);
        const startAngle = opts.startAngle ?? 90;
        const endAngle = opts.endAngle ?? -270;
        const pieData = preparePieData(chartData, {
          nameKey: xKey,
          valueKey: pieDataKey,
          maxSlices: opts.maxSlices ?? 7,
          groupSmallSlices: opts.groupSmallSlices !== false,
        });
        const labelMode = opts.labelMode ?? "percentage";
        const pieLabel =
          labelMode === "none"
            ? false
            : ({ name, value, percent }: { name: string; value: number; percent: number }) => {
                if (labelMode === "name") return name;
                if (labelMode === "value") return `${name} ${fmtAxis(value)}`;
                return `${name} ${(percent * 100).toFixed(0)}%`;
              };
        return (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
              <Pie
                data={pieData}
                dataKey={pieDataKey}
                nameKey={xKey}
                onClick={handlePieClick}
                style={clickCursor}
                cx="50%"
                cy="50%"
                innerRadius={`${innerPct}%`}
                outerRadius={`${outerPct}%`}
                startAngle={startAngle}
                endAngle={endAngle}
                paddingAngle={padAngle}
                label={pieLabel}
                labelLine={labelMode === "none" ? false : { stroke: "#94a3b8", strokeWidth: 1 }}
              >
                {pieData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="white" strokeWidth={2} />
                ))}
                {isDonut && (
                  <Label
                    content={<DonutCenterLabel data={pieData} yKey={pieDataKey} />}
                    position="center"
                  />
                )}
              </Pie>
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {showLegend && (
                <Legend
                  iconType="circle"
                  iconSize={8}
                  wrapperStyle={{ fontSize: 11 }}
                  formatter={(value: string) => <span className="text-slate-600">{value}</span>}
                />
              )}
            </PieChart>
          </ResponsiveContainer>
        );
      }

      // ── COMBO ───────────────────────────────────────────
      case "combo":
        return (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} onClick={handleCartesianClick} style={clickCursor} margin={{ top: 10, right: 20, bottom: 25, left: 10 }}>
              {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />}
              <XAxis dataKey={xKey} {...xAxisProps} />
              <YAxis yAxisId="left" {...yAxisProps} tickFormatter={fmtAxis} />
              {y2Key && <YAxis yAxisId="right" orientation="right" {...yAxisProps} tickFormatter={fmtAxis} />}
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {showLegend && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />}
              <Bar yAxisId="left" dataKey={yKey} fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={40}>
                {showDataLabels && <LabelList dataKey={yKey} position="top" style={{ fontSize: 9, fill: "#64748b" }} formatter={(v: number) => fmtAxis(v)} />}
              </Bar>
              {y2Key ? (
                <Line yAxisId="right" type={lineType as "linear" | "monotone" | "stepAfter"} dataKey={y2Key} stroke="#8b5cf6" strokeWidth={2.5} dot={{ r: 3, fill: "#8b5cf6" }} />
              ) : (
                <Line yAxisId="left" type={lineType as "linear" | "monotone" | "stepAfter"} dataKey={yKey} stroke="#8b5cf6" strokeWidth={2.5} dot={{ r: 3, fill: "#8b5cf6" }} />
              )}
              {renderReferenceLines(opts.referenceLines, y2Key ? "right" : "left")}
            </ComposedChart>
          </ResponsiveContainer>
        );

      // ── SCATTER / BUBBLE ────────────────────────────────
      case "scatter": {
        const zKey = opts.zColumn || widget.y2Column || "";
        const isBubble = (opts.bubble || sub === "bubble") && !!zKey;
        const xLabel = widget.xColumn || xKey;
        const yLabel = widget.yColumn || yKey;
        const trend = opts.showTrendLine || sub === "best_fit" ? linearRegression(chartData, { xKey, yKey }) : null;
        return (
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={tiny ? { top: 2, right: 2, bottom: 2, left: 2 } : { top: 10, right: 20, bottom: 30, left: 10 }}>
              {showGrid && <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />}
              {!tiny && (
                <XAxis type="number" dataKey={xKey} name={xLabel} {...commonAxisProps} tickFormatter={fmtAxis}>
                  <Label value={xLabel} position="insideBottom" offset={-15} style={{ fontSize: 10, fill: "#64748b", textAnchor: "middle" }} />
                </XAxis>
              )}
              {!tiny && (
                <YAxis type="number" dataKey={yKey} name={yLabel} {...yAxisProps} tickFormatter={fmtAxis}>
                  <Label value={yLabel} angle={-90} position="insideLeft" offset={-35} style={{ fontSize: 10, fill: "#64748b", textAnchor: "middle" }} />
                </YAxis>
              )}
              {isBubble && <ZAxis type="number" dataKey={zKey} range={[40, 400]} name={zKey} />}
              <Tooltip
                cursor={{ strokeDasharray: "3 3" }}
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {seriesNames.length > 0 ? (
                seriesNames.map((name, i) => (
                  <Scatter key={name} name={name} data={chartData} fill={COLORS[i % COLORS.length]} />
                ))
              ) : (
                <Scatter name={yLabel} data={chartData} fill="#3b82f6">
                  {showDataLabels && <LabelList dataKey={xKey} position="top" style={{ fontSize: 9, fill: "#64748b" }} />}
                </Scatter>
              )}
              {trend && (
                <ReferenceLine
                  ifOverflow="extendDomain"
                  segment={[trend.p1, trend.p2]}
                  stroke="#ef4444"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                />
              )}
              {showLegend && seriesNames.length > 0 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />}
            </ScatterChart>
          </ResponsiveContainer>
        );
      }

      // ── RADAR ───────────────────────────────────────────
      case "radar": {
        const { data: radarData, series: radarSeries } = prepareRadarData(coercedData, {
          subjectKey: xKey,
          valueKey: yKey,
          seriesKey: hasGroupBy ? widget.groupByColumn : undefined,
        });
        const domainMax = opts.domainMax && opts.domainMax > 0 ? opts.domainMax : "auto";
        const domainMin = opts.domainMin ?? 0;
        const fillOp = opts.fillOpacity ?? 0.25;
        return (
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={radarData} margin={{ top: 20, right: 30, bottom: 20, left: 30 }}>
              <PolarGrid stroke="#e2e8f0" />
              <PolarAngleAxis dataKey={xKey} tick={{ fontSize: 11, fill: "#475569" }} />
              <PolarRadiusAxis angle={90} domain={[domainMin, domainMax]} tick={{ fontSize: 9, fill: "#94a3b8" }} />
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {radarSeries.map((name, i) => (
                <Radar
                  key={name}
                  name={name}
                  dataKey={name}
                  stroke={COLORS[i % COLORS.length]}
                  fill={COLORS[i % COLORS.length]}
                  fillOpacity={fillOp}
                />
              ))}
              {showLegend && radarSeries.length > 1 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />}
            </RadarChart>
          </ResponsiveContainer>
        );
      }

      // ── RADIAL BAR ──────────────────────────────────────
      case "radial_bar": {
        const radialKey = seriesNames.length > 0 ? seriesNames[0] : yKey;
        const radialData = chartData.map((row, i) => ({
          name: String(row[xKey] ?? ""),
          value: Number(row[radialKey] ?? 0),
          fill: COLORS[i % COLORS.length],
        }));
        const innerPct = opts.innerRadius ?? 30;
        const outerPct = opts.outerRadius ?? 90;
        const startAngle = opts.startAngle ?? 90;
        const endAngle = opts.endAngle ?? -270;
        return (
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart
              data={radialData}
              cx="50%"
              cy="50%"
              innerRadius={`${innerPct}%`}
              outerRadius={`${outerPct}%`}
              startAngle={startAngle}
              endAngle={endAngle}
              barSize={12}
            >
              <PolarAngleAxis type="number" domain={[0, opts.domainMax && opts.domainMax > 0 ? opts.domainMax : "auto"]} tick={false} />
              <RadialBar background dataKey="value" cornerRadius={6}>
                {showDataLabels && <LabelList dataKey="value" position="insideStart" style={{ fontSize: 9, fill: "#ffffff" }} formatter={(v: number) => fmtAxis(v)} />}
              </RadialBar>
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {showLegend && (
                <Legend iconType="circle" iconSize={8} layout="vertical" verticalAlign="middle" align="right" wrapperStyle={{ fontSize: 11 }} />
              )}
            </RadialBarChart>
          </ResponsiveContainer>
        );
      }

      // ── TREEMAP ─────────────────────────────────────────
      case "treemap": {
        const treeKey = seriesNames.length > 0 ? seriesNames[0] : yKey;
        // Nested groups rows under their Group By column into parent rectangles.
        const treeGroupKey = sub === "nested" && hasGroupBy ? widget.groupByColumn : undefined;
        const treeData = prepareTreemapData(coercedData, { nameKey: xKey, valueKey: treeKey, groupKey: treeGroupKey }).map((d, i) => ({
          ...d,
          fill: COLORS[i % COLORS.length],
          children: d.children?.map((c) => ({ ...c, fill: COLORS[i % COLORS.length] })),
        }));
        return (
          <ResponsiveContainer width="100%" height="100%">
            <Treemap
              data={treeData}
              dataKey="size"
              nameKey="name"
              stroke="#ffffff"
              isAnimationActive={false}
            >
              {opts.showTooltip !== false && (
                <Tooltip
                  contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                  formatter={(value: number) => [fmtNumber(value), ""]}
                />
              )}
            </Treemap>
          </ResponsiveContainer>
        );
      }

      // ── FUNNEL ──────────────────────────────────────────
      case "funnel": {
        const funnelKey = seriesNames.length > 0 ? seriesNames[0] : yKey;
        const funnelData = prepareFunnelData(chartData, { nameKey: xKey, valueKey: funnelKey }).map((d, i) => ({
          ...d,
          fill: COLORS[i % COLORS.length],
        }));
        return (
          <ResponsiveContainer width="100%" height="100%">
            <FunnelChart margin={{ top: 10, right: 20, bottom: 10, left: 20 }}>
              {opts.showTooltip !== false && (
                <Tooltip
                  contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                  formatter={(value: number) => [fmtNumber(value), ""]}
                />
              )}
              <Funnel dataKey="value" data={funnelData} isAnimationActive={false}>
                {opts.showLabels !== false && (
                  <LabelList position="right" fill="#334155" stroke="none" dataKey="name" style={{ fontSize: 11 }} />
                )}
                {opts.showLabels !== false && (
                  <LabelList position="left" fill="#64748b" stroke="none" dataKey="value" style={{ fontSize: 10 }} formatter={(v: number) => fmtAxis(v)} />
                )}
              </Funnel>
            </FunnelChart>
          </ResponsiveContainer>
        );
      }

      // ── SANKEY ──────────────────────────────────────────
      case "sankey": {
        const sourceKey = widget.xColumn || xKey;
        const targetKey = opts.targetColumn || widget.groupByColumn || "";
        const valueKey = seriesNames.length > 0 ? seriesNames[0] : yKey;
        const graph = targetKey
          ? prepareSankeyData(coercedData, { sourceKey, targetKey, valueKey })
          : { nodes: [], links: [] };
        if (graph.nodes.length === 0 || graph.links.length === 0) {
          return (
            <div className="flex h-full items-center justify-center px-6 text-center text-xs text-slate-400">
              Sankey needs a source (X), a target (Group by), and a numeric value (Y).
            </div>
          );
        }
        return (
          <ResponsiveContainer width="100%" height="100%">
            <Sankey
              data={graph}
              nodePadding={opts.nodePadding ?? 20}
              nodeWidth={opts.nodeWidth ?? 12}
              link={{ stroke: "#cbd5e1", strokeOpacity: 0.4 }}
              node={{ fill: "#3b82f6" }}
              margin={{ top: 10, right: 60, bottom: 10, left: 10 }}
            >
              {opts.showTooltip !== false && (
                <Tooltip
                  contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                  formatter={(value: number) => [fmtNumber(value), ""]}
                />
              )}
            </Sankey>
          </ResponsiveContainer>
        );
      }

      default:
        return <div className="flex h-full items-center justify-center text-sm text-slate-400">Unknown widget type</div>;
    }
  };

  return (
    <div className="h-full w-full">
      {data.length === 0 ? (
        <div className="flex h-full items-center justify-center text-xs text-slate-400">
          No data available
        </div>
      ) : (
        renderChart()
      )}
    </div>
  );
}
