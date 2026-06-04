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
} from "recharts";
import type { WidgetConfig } from "./types";

const COLORS = ["#2563eb", "#60a5fa", "#93c5fd", "#bfdbfe", "#7c3aed", "#a78bfa", "#16a34a", "#ea580c"];

type Props = {
  widget: WidgetConfig;
  data: Array<Record<string, unknown>>;
  onEdit?: () => void;
  onDelete?: () => void;
};

function KpiWidget({ widget, data }: { widget: WidgetConfig; data: Props["data"] }) {
  const value = data.length > 0 ? data[0][widget.yKey] : "—";
  return (
    <div className="flex flex-col items-center justify-center py-4">
      <div className="text-3xl font-extrabold text-blue-600">{String(value)}</div>
      <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {widget.title}
      </div>
    </div>
  );
}

function TableWidget({ widget, data }: { widget: WidgetConfig; data: Props["data"] }) {
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
              <th
                key={col}
                className="border-b-2 border-slate-200 px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-500"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.slice(0, 20).map((row, i) => (
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

  const renderChart = () => {
    switch (widget.type) {
      case "kpi":
        return <KpiWidget widget={widget} data={data} />;
      case "table":
        return <TableWidget widget={widget} data={data} />;
      case "line":
        return (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={widget.xKey} stroke="#64748b" tick={{ fontSize: 11 }} />
              <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey={widget.yKey} stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        );
      case "bar":
        return (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={widget.xKey} stroke="#64748b" tick={{ fontSize: 11 }} />
              <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey={widget.yKey} fill="#2563eb" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        );
      case "area":
        return (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <AreaChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={widget.xKey} stroke="#64748b" tick={{ fontSize: 11 }} />
              <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Area type="monotone" dataKey={widget.yKey} stroke="#2563eb" fill="rgba(37,99,235,0.1)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        );
      case "pie":
        return (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <PieChart>
              <Pie
                data={data}
                dataKey={widget.yKey}
                nameKey={widget.xKey}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
              >
                {data.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        );
      default:
        return <div className="py-8 text-center text-sm text-slate-400">Unknown widget type</div>;
    }
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-700">{widget.title}</h4>
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
          No data available. Run the linked query to populate this widget.
        </div>
      ) : (
        renderChart()
      )}
    </div>
  );
}
