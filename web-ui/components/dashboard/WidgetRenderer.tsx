"use client";

import { useMemo } from "react";
import type { WidgetConfig, ChartClickEvent, VisualizationOptions } from "./types";
import { toNumber, type Row } from "@/lib/visualizations/dataTransforms";
import { EChartsWidget } from "./EChartsWidget";

const SCALE_DIVISORS = { hundreds: 100, thousands: 1_000, millions: 1_000_000 } as const;
const SCALE_SUFFIXES = { hundreds: "H", thousands: "K", millions: "M" } as const;

function fmtNumber(v: number, scale?: VisualizationOptions["valueScale"], currencySymbol = "$"): string {
  if (scale && scale !== "auto") {
    return `${currencySymbol}${(v / SCALE_DIVISORS[scale]).toLocaleString(undefined, { maximumFractionDigits: 1 })}${SCALE_SUFFIXES[scale]}`;
  }
  if (Math.abs(v) >= 1_000_000) return `${currencySymbol}${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${currencySymbol}${(v / 1_000).toFixed(0)}K`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
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

function coerceNumeric(data: Props["data"]): Props["data"] {
  if (data.length === 0) return data;
  const numericKeys = new Set<string>();
  const firstRow = data[0];
  for (const [k, v] of Object.entries(firstRow)) {
    if (typeof v === "number") {
      numericKeys.add(k);
      continue;
    }
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
}

/* ── KPI Card (mockup-quality) ──────────────────────────── */

function KpiWidget({ widget, data, operational = false }: { widget: WidgetConfig; data: Props["data"]; operational?: boolean }) {
  const yKey = getYKey(widget, data);
  const rawValue = data.length > 0 ? data[0][yKey] : null;
  const numVal = typeof rawValue === "number" ? rawValue : parseFloat(String(rawValue ?? "0"));
  const isCount = widget.aggregation === "count";

  const formatted = isNaN(numVal)
    ? String(rawValue ?? "\u2014")
    : isCount
      ? numVal.toLocaleString()
      : fmtNumber(numVal, widget.visualizationOptions?.valueScale, widget.visualizationOptions?.currencySymbol);

  const deltaValue = data.length > 0 ? Number(data[0].deltaPercent) : Number.NaN;
  const hasDelta = Number.isFinite(deltaValue);
  const direction = widget.visualizationOptions?.favorableDirection ?? "higher";
  const favorable = hasDelta && (direction === "higher" ? deltaValue > 0 : direction === "lower" ? deltaValue < 0 : false);
  const unfavorable = hasDelta && direction !== "neutral" && deltaValue !== 0 && !favorable;
  const aggColor =
    widget.aggregation === "sum"
      ? "bg-blue-100 text-blue-600"
      : widget.aggregation === "count"
        ? "bg-emerald-100 text-emerald-600"
        : widget.aggregation === "avg"
          ? "bg-violet-100 text-violet-600"
          : "bg-slate-100 text-slate-600";

  return (
    <div className={operational ? "flex h-full flex-col items-start justify-center px-1 py-1" : "flex h-full flex-col items-start justify-center px-5 py-4"}>
      {!operational && <div className="mb-1 flex items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{widget.title}</span>
        <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${aggColor}`}>{widget.aggregation}</span>
      </div>}
      <div className={operational ? "text-2xl font-semibold tracking-tight text-ink-primary" : "text-3xl font-extrabold tracking-tight text-slate-800"}>{formatted}</div>
      <div className="mt-1 flex items-center gap-1 text-[11px]">
        {hasDelta ? <>
          <span className={`font-semibold ${favorable ? "text-emerald-600" : unfavorable ? "text-rose-600" : "text-ink-tertiary"}`}>
            {deltaValue > 0 ? "↑" : deltaValue < 0 ? "↓" : "→"} {Math.abs(deltaValue).toFixed(1)}%
          </span>
          <span className="text-ink-tertiary">vs prior period</span>
        </> : <span className="text-ink-tertiary">No prior-period comparison</span>}
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
              <th key={col} className="border-b-2 border-slate-200 px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-500">{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.slice(0, 50).map((row, i) => (
            <tr key={i} className="hover:bg-slate-50">
              {columns.map((col) => (
                <td key={col} className="border-b border-slate-100 px-3 py-1.5 text-slate-700">{String(row[col] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Props = {
  widget: WidgetConfig;
  data: Array<Record<string, unknown>>;
  onElementClick?: (event: ChartClickEvent) => void;
  operational?: boolean;
};

export function WidgetRenderer({ widget, data, onElementClick, operational = false }: Props) {
  const xKey = getXKey(widget, data);
  const yKey = getYKey(widget, data);
  const y2Key = getY2Key(widget, data);

  const clickable =
    !!onElementClick &&
    widget.interactions?.enabled === true &&
    (widget.interactions?.clickAction ?? "none") !== "none";

  const coercedData = useMemo(() => coerceNumeric(data), [data]);
  const hasGroupBy =
    !!widget.groupByColumn && data.length > 0 && Object.keys(data[0] ?? {}).includes(widget.groupByColumn);

  const { chartData, seriesNames } = useMemo(() => {
    if (hasGroupBy && widget.groupByColumn) {
      return pivotData(coercedData, xKey, yKey, widget.groupByColumn);
    }
    return { chartData: coercedData, seriesNames: [] as string[] };
  }, [coercedData, xKey, yKey, hasGroupBy, widget.groupByColumn]);

  if (data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-slate-400">No data available</div>
    );
  }

  if (widget.type === "kpi") return <KpiWidget widget={widget} data={coercedData} operational={operational} />;
  if (widget.type === "table") return <TableWidget data={data} />;

  return (
    <EChartsWidget
      widget={widget}
      data={data}
      xKey={xKey}
      yKey={yKey}
      y2Key={y2Key}
      chartData={chartData}
      seriesNames={seriesNames}
      onElementClick={clickable ? onElementClick : undefined}
    />
  );
}
