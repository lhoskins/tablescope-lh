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
} from "recharts";
import type { WidgetConfig } from "./types";

const COLORS = ["#2563eb", "#60a5fa", "#7c3aed", "#16a34a", "#ea580c", "#0891b2", "#dc2626", "#ca8a04"];

type Props = {
  widget: WidgetConfig;
  data: Array<Record<string, unknown>>;
  onEdit?: () => void;
  onDelete?: () => void;
};

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

function KpiWidget({ widget, data }: { widget: WidgetConfig; data: Props["data"] }) {
  const yKey = getYKey(widget, data);
  const value = data.length > 0 ? data[0][yKey] : "\u2014";
  const formatted = typeof value === "number"
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : String(value ?? "\u2014");
  return (
    <div className="flex flex-col items-center justify-center py-4">
      <div className="text-3xl font-extrabold text-blue-600">{formatted}</div>
      <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {widget.title}
      </div>
      {widget.aggregation && (
        <div className="mt-0.5 text-[10px] text-slate-400">
          {widget.aggregation.toUpperCase()}({widget.yColumn})
        </div>
      )}
    </div>
  );
}

function TableWidget({ data }: { data: Props["data"] }) {
  const columns = useMemo(() => {
    if (data.length === 0) return [];
    return Object.keys(data[0]);
  }, [data]);

  return (
    <div className="max-h-[280px] overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
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
                <td key={col} className="border-b border-slate-100 px-3 py-2 text-slate-700">
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

export function WidgetRenderer({ widget, data, onEdit, onDelete }: Props) {
  const chartHeight = 220;
  const xKey = getXKey(widget, data);
  const yKey = getYKey(widget, data);
  const y2Key = getY2Key(widget, data);
  const hasGroupBy = !!widget.groupByColumn && data.length > 0 && Object.keys(data[0] ?? {}).includes(widget.groupByColumn);
  const sub = widget.chartSubtype ?? "";
  const isHorizontal = sub === "horizontal_bar" || sub === "stacked_horizontal";

  const { chartData, seriesNames } = useMemo(() => {
    if (hasGroupBy && widget.groupByColumn) {
      return pivotData(data, xKey, yKey, widget.groupByColumn);
    }
    return { chartData: data, seriesNames: [] as string[] };
  }, [data, xKey, yKey, hasGroupBy, widget.groupByColumn]);

  const stackId = (sub === "stacked_bar" || sub === "stacked_horizontal") ? "stack" : undefined;
  const lineType = sub === "smooth_line" ? "monotone" : sub === "step_line" ? "stepAfter" : "linear";

  const renderChart = () => {
    switch (widget.type) {
      case "kpi":
        return <KpiWidget widget={widget} data={data} />;
      case "table":
        return <TableWidget data={data} />;

      // ── LINE ─────────────────────────────────────────────────
      case "line":
        return (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={xKey} stroke="#64748b" tick={{ fontSize: 11 }} />
              <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
              <Tooltip />
              {seriesNames.length > 0 ? (
                seriesNames.map((name, i) => (
                  <Line key={name} type={lineType as "linear" | "monotone" | "stepAfter"} dataKey={name} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={{ r: 2 }} />
                ))
              ) : (
                <Line type={lineType as "linear" | "monotone" | "stepAfter"} dataKey={yKey} stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
              )}
              {seriesNames.length > 0 && <Legend />}
            </LineChart>
          </ResponsiveContainer>
        );

      // ── BAR (column, stacked, grouped, horizontal, stacked-horizontal) ──
      case "bar":
        return (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <BarChart data={chartData} layout={isHorizontal ? "vertical" : "horizontal"}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              {isHorizontal ? (
                <>
                  <YAxis type="category" dataKey={xKey} stroke="#64748b" tick={{ fontSize: 11 }} width={90} />
                  <XAxis type="number" stroke="#64748b" tick={{ fontSize: 11 }} />
                </>
              ) : (
                <>
                  <XAxis dataKey={xKey} stroke="#64748b" tick={{ fontSize: 11 }} />
                  <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
                </>
              )}
              <Tooltip />
              {seriesNames.length > 0 ? (
                seriesNames.map((name, i) => (
                  <Bar
                    key={name}
                    dataKey={name}
                    fill={COLORS[i % COLORS.length]}
                    radius={isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
                    stackId={stackId ?? (sub === "grouped_bar" ? undefined : "stack")}
                  />
                ))
              ) : (
                <Bar dataKey={yKey} fill="#2563eb" radius={isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} />
              )}
              {seriesNames.length > 0 && <Legend />}
            </BarChart>
          </ResponsiveContainer>
        );

      // ── AREA (regular, stacked) ──────────────────────────────
      case "area":
        return (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={xKey} stroke="#64748b" tick={{ fontSize: 11 }} />
              <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
              <Tooltip />
              {seriesNames.length > 0 ? (
                seriesNames.map((name, i) => (
                  <Area
                    key={name}
                    type="monotone"
                    dataKey={name}
                    stroke={COLORS[i % COLORS.length]}
                    fill={`${COLORS[i % COLORS.length]}20`}
                    strokeWidth={2}
                    stackId={sub === "stacked_area" ? "stack" : undefined}
                  />
                ))
              ) : (
                <Area type="monotone" dataKey={yKey} stroke="#2563eb" fill="rgba(37,99,235,0.1)" strokeWidth={2} />
              )}
              {seriesNames.length > 0 && <Legend />}
            </AreaChart>
          </ResponsiveContainer>
        );

      // ── PIE / DONUT ──────────────────────────────────────────
      case "pie": {
        const isDonut = sub === "donut";
        return (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <PieChart>
              <Pie
                data={chartData}
                dataKey={seriesNames.length > 0 ? seriesNames[0] : yKey}
                nameKey={xKey}
                cx="50%"
                cy="50%"
                innerRadius={isDonut ? 50 : 0}
                outerRadius={80}
                label={({ name, percent }: { name: string; percent: number }) => `${name} ${(percent * 100).toFixed(0)}%`}
              >
                {chartData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        );
      }

      // ── COMBO (bar + line) ───────────────────────────────────
      case "combo":
        return (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={xKey} stroke="#64748b" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="left" stroke="#64748b" tick={{ fontSize: 11 }} />
              {y2Key && <YAxis yAxisId="right" orientation="right" stroke="#7c3aed" tick={{ fontSize: 11 }} />}
              <Tooltip />
              <Legend />
              <Bar yAxisId="left" dataKey={yKey} fill="#2563eb" radius={[4, 4, 0, 0]} />
              {y2Key && (
                <Line yAxisId="right" type="monotone" dataKey={y2Key} stroke="#7c3aed" strokeWidth={2} dot={{ r: 3 }} />
              )}
              {!y2Key && (
                <Line yAxisId="left" type="monotone" dataKey={yKey} stroke="#7c3aed" strokeWidth={2} dot={{ r: 3 }} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        );

      default:
        return <div className="py-8 text-center text-sm text-slate-400">Unknown widget type</div>;
    }
  };

  return (
    <div className="h-full rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h4 className="text-sm font-semibold text-slate-700">{widget.title}</h4>
          {widget.aggregation && widget.yColumn && (
            <div className="mt-0.5 flex items-center gap-1.5">
              <span className="inline-block rounded bg-sky-100 px-1.5 py-0.5 text-[9px] font-bold text-sky-700">
                {widget.aggregation.toUpperCase()}({widget.yColumn})
              </span>
              {widget.chartSubtype && (
                <span className="inline-block rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-600">
                  {widget.chartSubtype.replace(/_/g, " ")}
                </span>
              )}
              {widget.dateGranularity && (
                <span className="inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-bold text-amber-700">
                  {widget.dateGranularity}
                </span>
              )}
              {widget.groupByColumn && (
                <>
                  <span className="text-[9px] text-slate-400">by</span>
                  <span className="inline-block rounded bg-purple-100 px-1.5 py-0.5 text-[9px] font-bold text-purple-700">
                    {widget.groupByColumn}
                  </span>
                </>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-1">
          {onEdit && (
            <button onClick={onEdit} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" title="Edit">
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" /></svg>
            </button>
          )}
          {onDelete && (
            <button onClick={onDelete} className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-500" title="Delete">
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
            </button>
          )}
        </div>
      </div>
      {data.length === 0 ? (
        <div className="flex h-[200px] items-center justify-center text-sm text-slate-400">
          No data available
        </div>
      ) : (
        renderChart()
      )}
    </div>
  );
}
