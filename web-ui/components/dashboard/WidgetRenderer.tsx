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
} from "recharts";
import type { WidgetConfig } from "./types";

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

export function WidgetRenderer({ widget, data }: Props) {
  const xKey = getXKey(widget, data);
  const yKey = getYKey(widget, data);
  const y2Key = getY2Key(widget, data);
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

  const stackId = (sub === "stacked_bar" || sub === "stacked_horizontal") ? "stack" : undefined;
  const lineType = sub === "smooth_line" ? "monotone" : sub === "step_line" ? "stepAfter" : "linear";

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

  const barXAxisProps = {
    ...commonAxisProps,
    interval: 0 as const,
    tick: { fontSize: 11, fill: "#334155" },
    height: 40,
  };

  const yAxisProps = {
    ...commonAxisProps,
    width: 55,
    tick: { fontSize: 11, fill: "#334155" },
  };

  const renderChart = () => {
    switch (widget.type) {
      case "kpi":
        return <KpiWidget widget={widget} data={data} />;
      case "table":
        return <TableWidget data={data} />;

      // ── LINE ────────────────────────────────────────────
      case "line":
        return (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 25, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey={xKey} {...xAxisProps} />
              <YAxis {...yAxisProps} tickFormatter={fmtAxis} />
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {seriesNames.length > 0 ? (
                seriesNames.map((name, i) => (
                  <Line key={name} type={lineType as "linear" | "monotone" | "stepAfter"} dataKey={name} stroke={COLORS[i % COLORS.length]} strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} />
                ))
              ) : (
                <Line type={lineType as "linear" | "monotone" | "stepAfter"} dataKey={yKey} stroke="#3b82f6" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} />
              )}
              {seriesNames.length > 0 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />}
            </LineChart>
          </ResponsiveContainer>
        );

      // ── BAR ─────────────────────────────────────────────
      case "bar": {
        const barXLabel = widget.xColumn || xKey;
        const barYLabel = widget.yColumn || yKey;
        return (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} layout={isHorizontal ? "vertical" : "horizontal"} margin={{ top: 10, right: 20, bottom: 40, left: isHorizontal ? 10 : 50 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={!isHorizontal} horizontal={isHorizontal} />
              {isHorizontal ? (
                <>
                  <YAxis type="category" dataKey={xKey} {...commonAxisProps} width={100}>
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
                    radius={isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
                    stackId={stackId ?? (sub === "grouped_bar" ? undefined : "stack")}
                    maxBarSize={48}
                  />
                ))
              ) : (
                <Bar dataKey={yKey} fill="#3b82f6" radius={isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={48} />
              )}
              {seriesNames.length > 0 && <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 11 }} />}
            </BarChart>
          </ResponsiveContainer>
        );
      }

      // ── AREA ────────────────────────────────────────────
      case "area":
        return (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 20, bottom: 25, left: 10 }}>
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
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey={xKey} {...xAxisProps} />
              <YAxis {...yAxisProps} tickFormatter={fmtAxis} />
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              {seriesNames.length > 0 ? (
                seriesNames.map((name, i) => (
                  <Area
                    key={name}
                    type="monotone"
                    dataKey={name}
                    stroke={COLORS[i % COLORS.length]}
                    fill={`url(#grad-${i})`}
                    strokeWidth={2}
                    stackId={sub === "stacked_area" ? "stack" : undefined}
                  />
                ))
              ) : (
                <Area type="monotone" dataKey={yKey} stroke="#3b82f6" fill="url(#grad-default)" strokeWidth={2} />
              )}
              {seriesNames.length > 0 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />}
            </AreaChart>
          </ResponsiveContainer>
        );

      // ── PIE / DONUT ─────────────────────────────────────
      case "pie": {
        const isDonut = sub === "donut";
        const pieDataKey = seriesNames.length > 0 ? seriesNames[0] : yKey;
        return (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
              <Pie
                data={chartData}
                dataKey={pieDataKey}
                nameKey={xKey}
                cx="50%"
                cy="50%"
                innerRadius={isDonut ? "55%" : 0}
                outerRadius="80%"
                paddingAngle={isDonut ? 2 : 0}
                label={({ name, percent }: { name: string; percent: number }) =>
                  `${name} ${(percent * 100).toFixed(0)}%`
                }
                labelLine={{ stroke: "#94a3b8", strokeWidth: 1 }}
              >
                {chartData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="white" strokeWidth={2} />
                ))}
                {isDonut && (
                  <Label
                    content={<DonutCenterLabel data={chartData} yKey={pieDataKey} />}
                    position="center"
                  />
                )}
              </Pie>
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              <Legend
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: 11 }}
                formatter={(value: string) => <span className="text-slate-600">{value}</span>}
              />
            </PieChart>
          </ResponsiveContainer>
        );
      }

      // ── COMBO ───────────────────────────────────────────
      case "combo":
        return (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 10, right: 20, bottom: 25, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey={xKey} {...xAxisProps} />
              <YAxis yAxisId="left" {...yAxisProps} tickFormatter={fmtAxis} />
              {y2Key && <YAxis yAxisId="right" orientation="right" {...yAxisProps} tickFormatter={fmtAxis} />}
              <Tooltip
                contentStyle={{ fontSize: 11, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", border: "1px solid #e2e8f0" }}
                formatter={(value: number) => [fmtNumber(value), ""]}
              />
              <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="left" dataKey={yKey} fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={40} />
              {y2Key ? (
                <Line yAxisId="right" type="monotone" dataKey={y2Key} stroke="#8b5cf6" strokeWidth={2.5} dot={{ r: 3, fill: "#8b5cf6" }} />
              ) : (
                <Line yAxisId="left" type="monotone" dataKey={yKey} stroke="#8b5cf6" strokeWidth={2.5} dot={{ r: 3, fill: "#8b5cf6" }} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        );

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
