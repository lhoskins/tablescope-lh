"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { WidgetConfig, WidgetType, WidgetFilter, ColumnInfo } from "./types";

const WIDGET_TYPES: { type: WidgetType; label: string; icon: string }[] = [
  { type: "bar", label: "Bar", icon: "\u{1F4CA}" },
  { type: "line", label: "Line", icon: "\u{1F4C8}" },
  { type: "pie", label: "Pie", icon: "\u{1F369}" },
  { type: "area", label: "Area", icon: "\u{1F4C9}" },
  { type: "kpi", label: "KPI", icon: "\u{1F522}" },
  { type: "table", label: "Table", icon: "\u{1F4CB}" },
];

const AGGREGATIONS = ["sum", "avg", "count", "min", "max"] as const;
const GRANULARITIES = ["day", "week", "month", "quarter", "year"] as const;
const SORT_OPTIONS = [
  { value: "x_asc", label: "X Axis (ascending)" },
  { value: "x_desc", label: "X Axis (descending)" },
  { value: "y_desc", label: "Y Axis (descending)" },
  { value: "y_asc", label: "Y Axis (ascending)" },
];
const FILTER_OPERATORS = [
  { value: "eq", label: "equals" },
  { value: "neq", label: "not equals" },
  { value: "gt", label: "greater than" },
  { value: "lt", label: "less than" },
  { value: "gte", label: ">=" },
  { value: "lte", label: "<=" },
  { value: "between", label: "between" },
  { value: "in", label: "in (comma-sep)" },
  { value: "not_in", label: "not in" },
  { value: "contains", label: "contains" },
];

type SavedQuery = { id: number; name: string };
type Datasource = { viewName: string; fileName: string };

type Props = {
  projectId: number;
  savedQueries: SavedQuery[];
  datasources: Datasource[];
  editingWidget?: WidgetConfig | null;
  onSave: (widget: WidgetConfig) => void;
  onCancel: () => void;
};

export function WidgetConfigPanel({
  projectId,
  savedQueries,
  datasources,
  editingWidget,
  onSave,
  onCancel,
}: Props) {
  // Form state
  const [title, setTitle] = useState(editingWidget?.title ?? "");
  const [chartType, setChartType] = useState<WidgetType>(editingWidget?.type ?? "bar");
  const [sourceKind, setSourceKind] = useState<"datasource" | "query">(
    editingWidget?.dataSource.kind === "query" ? "query" : "datasource"
  );
  const [sourceId, setSourceId] = useState(
    editingWidget?.dataSource.viewName ?? editingWidget?.dataSource.queryId?.toString() ?? ""
  );
  const [xColumn, setXColumn] = useState(editingWidget?.xColumn ?? "");
  const [yColumn, setYColumn] = useState(editingWidget?.yColumn ?? "");
  const [aggregation, setAggregation] = useState<(typeof AGGREGATIONS)[number]>(
    editingWidget?.aggregation ?? "sum"
  );
  const [dateGranularity, setDateGranularity] = useState<string>(
    editingWidget?.dateGranularity ?? ""
  );
  const [groupByColumn, setGroupByColumn] = useState(editingWidget?.groupByColumn ?? "");
  const [sortBy, setSortBy] = useState(editingWidget?.sortBy ?? "x_asc");
  const [limit, setLimit] = useState<string>(editingWidget?.limit?.toString() ?? "");
  const [filters, setFilters] = useState<WidgetFilter[]>(editingWidget?.filters ?? []);
  const [colSpan, setColSpan] = useState(editingWidget?.colSpan ?? 6);

  // Derive viewName for schema fetch
  const viewName = sourceKind === "datasource" ? sourceId : "";

  // Fetch schema when datasource is selected
  const { data: schemaData } = useQuery({
    queryKey: ["datasource-schema", projectId, viewName],
    queryFn: async () => {
      if (!viewName) return { columns: [] };
      const resp = await apiClient.get<{ columns: ColumnInfo[] }>(
        `/api/projects/${projectId}/dashboards/schema/${viewName}`
      );
      return resp;
    },
    enabled: !!viewName,
  });

  const columns: ColumnInfo[] = schemaData?.columns ?? [];
  const dateColumns = columns.filter((c) => c.type === "date");
  const numericColumns = columns.filter((c) => c.type === "number");
  const stringColumns = columns.filter((c) => c.type === "string");
  const xColumnType = columns.find((c) => c.name === xColumn)?.type;

  // Auto-select first sensible columns when schema loads
  useEffect(() => {
    if (columns.length > 0 && !editingWidget) {
      if (!xColumn) {
        const firstDate = dateColumns[0];
        const firstString = stringColumns[0];
        if (firstDate) {
          setXColumn(firstDate.name);
          setDateGranularity("month");
        } else if (firstString) {
          setXColumn(firstString.name);
        }
      }
      if (!yColumn) {
        const firstNum = numericColumns[0];
        if (firstNum) setYColumn(firstNum.name);
      }
    }
  }, [columns.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSave = useCallback(() => {
    if (!title.trim() || !xColumn || !yColumn) return;
    const widget: WidgetConfig = {
      id: editingWidget?.id ?? `w-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      type: chartType,
      title,
      dataSource:
        sourceKind === "query"
          ? { kind: "query", queryId: Number(sourceId) || 0 }
          : { kind: "datasource", viewName: sourceId },
      xColumn,
      xColumnType: xColumnType as "date" | "string" | "number" | undefined,
      dateGranularity: xColumnType === "date" && dateGranularity ? (dateGranularity as WidgetConfig["dateGranularity"]) : undefined,
      yColumn,
      aggregation,
      groupByColumn: groupByColumn || undefined,
      sortBy: sortBy as WidgetConfig["sortBy"],
      limit: limit ? parseInt(limit, 10) : undefined,
      filters,
      colSpan,
      position: editingWidget?.position ?? 0,
    };
    onSave(widget);
  }, [title, chartType, sourceKind, sourceId, xColumn, xColumnType, dateGranularity, yColumn, aggregation, groupByColumn, sortBy, limit, filters, colSpan, editingWidget, onSave]);

  const addFilter = () => {
    setFilters([...filters, { column: columns[0]?.name ?? "", operator: "eq", value: "" }]);
  };
  const removeFilter = (idx: number) => {
    setFilters(filters.filter((_, i) => i !== idx));
  };
  const updateFilter = (idx: number, patch: Partial<WidgetFilter>) => {
    setFilters(filters.map((f, i) => (i === idx ? { ...f, ...patch } : f)));
  };

  const canSave = title.trim() && xColumn && yColumn && sourceId;

  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
        <h3 className="text-sm font-bold text-slate-800">
          {editingWidget ? "Edit Widget" : "Add Widget"}
        </h3>
        <button onClick={onCancel} className="text-xs text-slate-400 hover:text-slate-600">
          Cancel
        </button>
      </div>

      <div className="grid grid-cols-12 gap-0">
        {/* Left: Configuration Form */}
        <div className="col-span-12 border-slate-100 p-5 lg:col-span-5 lg:border-r">
          {/* Title */}
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Widget Title</label>
            <input
              className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm outline-none focus:border-blue-500"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Monthly Revenue Trend"
            />
          </div>

          {/* Chart Type */}
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Chart Type</label>
            <div className="grid grid-cols-3 gap-1.5">
              {WIDGET_TYPES.map((wt) => (
                <button
                  key={wt.type}
                  type="button"
                  onClick={() => setChartType(wt.type)}
                  className={`rounded-lg border p-2 text-center text-xs transition ${
                    chartType === wt.type
                      ? "border-blue-600 bg-blue-50 font-semibold text-blue-700"
                      : "border-slate-200 text-slate-600 hover:border-blue-300"
                  }`}
                >
                  <div className="text-base">{wt.icon}</div>
                  <div className="mt-0.5 text-[10px]">{wt.label}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Data Source */}
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Data Source</label>
            <select
              className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-xs outline-none focus:border-blue-500"
              value={`${sourceKind}:${sourceId}`}
              onChange={(e) => {
                const [kind, id] = e.target.value.split(":");
                setSourceKind(kind as "datasource" | "query");
                setSourceId(id);
                setXColumn("");
                setYColumn("");
                setGroupByColumn("");
              }}
            >
              <option value="datasource:">Select a data source...</option>
              {datasources.map((ds) => (
                <option key={ds.viewName} value={`datasource:${ds.viewName}`}>
                  Datasource: {ds.fileName}
                </option>
              ))}
              {savedQueries.map((q) => (
                <option key={q.id} value={`query:${q.id}`}>
                  Query: {q.name}
                </option>
              ))}
            </select>
          </div>

          {/* Separator */}
          <div className="my-3 border-t border-slate-100" />
          <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Axis &amp; Aggregation
          </p>

          {/* X Axis */}
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">
              X Axis (Category / Dimension)
            </label>
            {columns.length > 0 ? (
              <select
                className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-xs outline-none focus:border-blue-500"
                value={xColumn}
                onChange={(e) => {
                  setXColumn(e.target.value);
                  const col = columns.find((c) => c.name === e.target.value);
                  if (col?.type === "date") setDateGranularity("month");
                  else setDateGranularity("");
                }}
              >
                <option value="">Select column...</option>
                {columns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name} ({c.type})
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-xs outline-none focus:border-blue-500"
                value={xColumn}
                onChange={(e) => setXColumn(e.target.value)}
                placeholder="Column name (e.g. region)"
              />
            )}
          </div>

          {/* Date Granularity (shown when X is a date) */}
          {xColumnType === "date" && (
            <div className="mb-3 rounded-lg border border-blue-100 bg-blue-50 p-3">
              <label className="mb-1 block text-[11px] font-semibold text-blue-700">
                Date Granularity
              </label>
              <div className="flex flex-wrap gap-1">
                {GRANULARITIES.map((g) => (
                  <button
                    key={g}
                    type="button"
                    onClick={() => setDateGranularity(g)}
                    className={`rounded-md border px-2.5 py-1 text-[10px] font-semibold transition ${
                      dateGranularity === g
                        ? "border-blue-600 bg-blue-600 text-white"
                        : "border-slate-200 text-slate-600 hover:border-blue-300"
                    }`}
                  >
                    {g.charAt(0).toUpperCase() + g.slice(1)}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-[10px] text-blue-600">
                Date column detected — groups time periods
              </p>
            </div>
          )}

          {/* Y Axis */}
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">
              Y Axis (Measure / Value)
            </label>
            {columns.length > 0 ? (
              <select
                className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-xs outline-none focus:border-blue-500"
                value={yColumn}
                onChange={(e) => setYColumn(e.target.value)}
              >
                <option value="">Select column...</option>
                {numericColumns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
                {/* Also allow non-numeric for COUNT */}
                {stringColumns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name} (string)
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-xs outline-none focus:border-blue-500"
                value={yColumn}
                onChange={(e) => setYColumn(e.target.value)}
                placeholder="Column name (e.g. amount)"
              />
            )}
          </div>

          {/* Aggregation */}
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">
              Aggregation
            </label>
            <div className="flex flex-wrap gap-1">
              {AGGREGATIONS.map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAggregation(a)}
                  className={`rounded-md border px-2.5 py-1 text-[10px] font-bold uppercase transition ${
                    aggregation === a
                      ? "border-blue-600 bg-blue-600 text-white"
                      : "border-slate-200 text-slate-600 hover:border-blue-300"
                  }`}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>

          {/* Group By */}
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">
              Group By / Color By (optional)
            </label>
            {columns.length > 0 ? (
              <select
                className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-xs outline-none focus:border-blue-500"
                value={groupByColumn}
                onChange={(e) => setGroupByColumn(e.target.value)}
              >
                <option value="">None — single series</option>
                {stringColumns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-xs outline-none focus:border-blue-500"
                value={groupByColumn}
                onChange={(e) => setGroupByColumn(e.target.value)}
                placeholder="Optional (e.g. category)"
              />
            )}
            <p className="mt-0.5 text-[10px] text-slate-400">
              Creates multiple series/bars/slices colored by this dimension
            </p>
          </div>

          {/* Sort & Limit */}
          <div className="my-3 border-t border-slate-100" />
          <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Sort &amp; Limit
          </p>
          <div className="mb-3 grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-slate-600">Sort</label>
              <select
                className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as "x_asc" | "x_desc" | "y_asc" | "y_desc")}
              >
                {SORT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-slate-600">Top N</label>
              <select
                className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
              >
                <option value="">No limit</option>
                <option value="5">Top 5</option>
                <option value="10">Top 10</option>
                <option value="20">Top 20</option>
                <option value="50">Top 50</option>
                <option value="100">Top 100</option>
              </select>
            </div>
          </div>

          {/* Widget Filters */}
          <div className="my-3 border-t border-slate-100" />
          <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Widget Filters
          </p>
          {filters.map((f, idx) => (
            <div key={idx} className="mb-2 flex items-center gap-1.5 rounded-md bg-slate-50 p-2">
              <select
                className="flex-1 rounded border border-slate-200 px-1.5 py-1 text-[11px]"
                value={f.column}
                onChange={(e) => updateFilter(idx, { column: e.target.value })}
              >
                {columns.length > 0
                  ? columns.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.name}
                      </option>
                    ))
                  : <option value={f.column}>{f.column}</option>
                }
              </select>
              <select
                className="rounded border border-slate-200 px-1.5 py-1 text-[11px]"
                value={f.operator}
                onChange={(e) => updateFilter(idx, { operator: e.target.value })}
              >
                {FILTER_OPERATORS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <input
                className="flex-1 rounded border border-slate-200 px-1.5 py-1 text-[11px]"
                value={String(f.value)}
                onChange={(e) => updateFilter(idx, { value: e.target.value })}
                placeholder="value"
              />
              {f.operator === "between" && (
                <input
                  className="w-16 rounded border border-slate-200 px-1.5 py-1 text-[11px]"
                  value={f.value2?.toString() ?? ""}
                  onChange={(e) => updateFilter(idx, { value2: Number(e.target.value) || 0 })}
                  placeholder="max"
                />
              )}
              <button
                type="button"
                onClick={() => removeFilter(idx)}
                className="text-xs text-red-400 hover:text-red-600"
              >
                x
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addFilter}
            className="text-[11px] font-medium text-blue-600 hover:underline"
          >
            + Add Filter
          </button>

          {/* Widget Size */}
          <div className="my-3 border-t border-slate-100" />
          <div className="mb-3">
            <label className="mb-1 block text-[11px] font-semibold text-slate-600">Widget Size</label>
            <div className="flex gap-1.5">
              {[
                { label: "Small (1/4)", val: 3 },
                { label: "Medium (1/2)", val: 6 },
                { label: "Large (2/3)", val: 8 },
                { label: "Full", val: 12 },
              ].map((s) => (
                <button
                  key={s.val}
                  type="button"
                  onClick={() => setColSpan(s.val)}
                  className={`rounded-md border px-2 py-1 text-[10px] font-semibold transition ${
                    colSpan === s.val
                      ? "border-blue-600 bg-blue-600 text-white"
                      : "border-slate-200 text-slate-600 hover:border-blue-300"
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right: Summary / Save */}
        <div className="col-span-12 p-5 lg:col-span-7">
          <div className="mb-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <h4 className="mb-2 text-xs font-bold text-slate-700">Configuration Summary</h4>
            <div className="space-y-1 text-[11px] text-slate-600">
              <div>
                <span className="font-semibold">Chart:</span> {chartType}
              </div>
              <div>
                <span className="font-semibold">Source:</span>{" "}
                {sourceKind === "datasource" ? sourceId : `Query #${sourceId}`}
              </div>
              {xColumn && (
                <div>
                  <span className="font-semibold">X:</span> {xColumn}
                  {dateGranularity && (
                    <span className="ml-1 inline-block rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-bold text-blue-700">
                      {dateGranularity}
                    </span>
                  )}
                </div>
              )}
              {yColumn && (
                <div>
                  <span className="font-semibold">Y:</span>{" "}
                  <span className="inline-block rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-bold text-sky-700">
                    {aggregation.toUpperCase()}({yColumn})
                  </span>
                </div>
              )}
              {groupByColumn && (
                <div>
                  <span className="font-semibold">Group By:</span> {groupByColumn}
                </div>
              )}
              {filters.length > 0 && (
                <div>
                  <span className="font-semibold">Filters:</span> {filters.length} active
                </div>
              )}
              {limit && (
                <div>
                  <span className="font-semibold">Limit:</span> Top {limit}
                </div>
              )}
            </div>
          </div>

          {columns.length > 0 && (
            <div className="mb-3 rounded-lg border border-slate-200 bg-white p-3">
              <h4 className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                Detected Columns ({columns.length})
              </h4>
              <div className="flex flex-wrap gap-1">
                {columns.map((c) => (
                  <span
                    key={c.name}
                    className={`inline-block rounded px-2 py-0.5 text-[10px] font-semibold ${
                      c.type === "date"
                        ? "bg-amber-100 text-amber-700"
                        : c.type === "number"
                        ? "bg-green-100 text-green-700"
                        : "bg-blue-100 text-blue-700"
                    }`}
                  >
                    {c.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onCancel}
              className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!canSave}
              className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
            >
              {editingWidget ? "Save Changes" : "Add Widget"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
