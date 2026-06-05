"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { WidgetConfig, WidgetType, ChartSubtype, WidgetFilter, ColumnInfo } from "./types";

// ── Chart type / subtype definitions ────────────────────────────────
type SubtypeDef = { value: ChartSubtype | ""; label: string };
type ChartTypeDef = { type: WidgetType; label: string; icon: string; subtypes: SubtypeDef[] };

const CHART_TYPES: ChartTypeDef[] = [
  {
    type: "bar", label: "Bar", icon: "\u{1F4CA}",
    subtypes: [
      { value: "column", label: "Column (vertical)" },
      { value: "stacked_bar", label: "Stacked Column" },
      { value: "grouped_bar", label: "Grouped (side-by-side)" },
      { value: "horizontal_bar", label: "Horizontal Bar" },
      { value: "stacked_horizontal", label: "Stacked Horizontal" },
    ],
  },
  {
    type: "line", label: "Line", icon: "\u{1F4C8}",
    subtypes: [
      { value: "", label: "Straight Line" },
      { value: "smooth_line", label: "Smooth / Spline" },
      { value: "step_line", label: "Step Line" },
    ],
  },
  {
    type: "area", label: "Area", icon: "\u{1F4C9}",
    subtypes: [
      { value: "", label: "Area" },
      { value: "stacked_area", label: "Stacked Area" },
    ],
  },
  {
    type: "pie", label: "Pie", icon: "\u{1F369}",
    subtypes: [
      { value: "", label: "Pie" },
      { value: "donut", label: "Donut" },
    ],
  },
  {
    type: "combo", label: "Combo", icon: "\u{1F4CA}\u{1F4C8}",
    subtypes: [
      { value: "bar_line", label: "Bar + Line Overlay" },
    ],
  },
  { type: "kpi", label: "KPI", icon: "\u{1F522}", subtypes: [] },
  { type: "table", label: "Table", icon: "\u{1F4CB}", subtypes: [] },
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
  { value: "in", label: "in (comma-sep)" },
  { value: "contains", label: "contains" },
];

type SavedQuery = { id: number; name: string; sql_text?: string | null };
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
  const [title, setTitle] = useState(editingWidget?.title ?? "");
  const [chartType, setChartType] = useState<WidgetType>(editingWidget?.type ?? "bar");
  const [chartSubtype, setChartSubtype] = useState<ChartSubtype | "">(editingWidget?.chartSubtype ?? "column");
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
  // Combo chart Y2
  const [y2Column, setY2Column] = useState(editingWidget?.y2Column ?? "");
  const [y2Aggregation, setY2Aggregation] = useState<(typeof AGGREGATIONS)[number]>(
    editingWidget?.y2Aggregation ?? "avg"
  );

  // Derive viewName for schema fetch — works for datasources directly
  const viewName = sourceKind === "datasource" ? sourceId : "";

  // For queries: execute the query to discover columns
  const selectedQuery = sourceKind === "query" ? savedQueries.find((q) => q.id === Number(sourceId)) : null;

  // Fetch schema for datasource
  const { data: schemaData } = useQuery({
    queryKey: ["datasource-schema", projectId, viewName],
    queryFn: async () => {
      if (!viewName) return { columns: [] };
      return apiClient.get<{ columns: ColumnInfo[] }>(
        `/api/projects/${projectId}/dashboards/schema/${viewName}`
      );
    },
    enabled: !!viewName,
  });

  // Fetch columns from a query by executing it with LIMIT 1
  const { data: queryColumnsData } = useQuery({
    queryKey: ["query-columns", projectId, selectedQuery?.id],
    queryFn: async () => {
      if (!selectedQuery) return { columns: [] as ColumnInfo[] };
      // Get the saved query's datasource to use as tableName
      const sql = selectedQuery.sql_text;
      if (!sql) return { columns: [] as ColumnInfo[] };
      // Execute query with limit 1 to get columns
      const limitedSql = sql.includes("LIMIT") ? sql : `${sql} LIMIT 1`;
      // We need to find which table this query references
      const tableMatch = sql.match(/FROM\s+"?([A-Za-z0-9_]+)"?/i);
      const tableName = tableMatch ? tableMatch[1] : "";
      if (!tableName) return { columns: [] as ColumnInfo[] };
      try {
        const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
          "/api/query/datasource",
          { tableName, limit: 1, project_id: projectId, sql: limitedSql }
        );
        const cols: ColumnInfo[] = (resp.columns ?? []).map((name: string) => {
          const row = resp.rows?.[0];
          const val = row?.[name];
          let type: ColumnInfo["type"] = "string";
          if (typeof val === "number") type = "number";
          else if (typeof val === "string" && /^\d{4}-\d{2}-\d{2}/.test(val)) type = "date";
          return { name, type };
        });
        return { columns: cols };
      } catch {
        return { columns: [] as ColumnInfo[] };
      }
    },
    enabled: sourceKind === "query" && !!selectedQuery,
  });

  const columns: ColumnInfo[] = sourceKind === "query"
    ? (queryColumnsData?.columns ?? [])
    : (schemaData?.columns ?? []);

  const dateColumns = columns.filter((c) => c.type === "date");
  const numericColumns = columns.filter((c) => c.type === "number");
  const stringColumns = columns.filter((c) => c.type === "string");
  const xColumnType = columns.find((c) => c.name === xColumn)?.type;

  const currentChartDef = CHART_TYPES.find((ct) => ct.type === chartType);

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
      chartSubtype: chartSubtype || undefined,
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
      y2Column: chartType === "combo" && y2Column ? y2Column : undefined,
      y2Aggregation: chartType === "combo" && y2Column ? y2Aggregation : undefined,
      groupByColumn: groupByColumn || undefined,
      sortBy: sortBy as WidgetConfig["sortBy"],
      limit: limit ? parseInt(limit, 10) : undefined,
      filters,
      colSpan,
      position: editingWidget?.position ?? 0,
      gridW: editingWidget?.gridW,
      gridH: editingWidget?.gridH,
      gridX: editingWidget?.gridX,
      gridY: editingWidget?.gridY,
    };
    onSave(widget);
  }, [title, chartType, chartSubtype, sourceKind, sourceId, xColumn, xColumnType, dateGranularity, yColumn, aggregation, y2Column, y2Aggregation, groupByColumn, sortBy, limit, filters, colSpan, editingWidget, onSave]);

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

  // Handle chart type change — auto-set default subtype
  const handleChartTypeChange = (type: WidgetType) => {
    setChartType(type);
    const def = CHART_TYPES.find((ct) => ct.type === type);
    if (def && def.subtypes.length > 0) {
      setChartSubtype(def.subtypes[0].value as ChartSubtype);
    } else {
      setChartSubtype("");
    }
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-bold text-slate-800">
          {editingWidget ? "Edit Widget" : "Add Widget"}
        </h3>
        <button onClick={onCancel} className="text-xs font-medium text-slate-500 hover:text-slate-700">
          Cancel
        </button>
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* Left: Config Form */}
        <div className="col-span-8 space-y-4">
          {/* Title */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-slate-600">Widget Title</label>
            <input
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-xs outline-none focus:border-blue-500"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Monthly Revenue Trend"
            />
          </div>

          {/* Chart Type */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-slate-600">Chart Type</label>
            <div className="flex flex-wrap gap-1.5">
              {CHART_TYPES.map((ct) => (
                <button
                  key={ct.type}
                  type="button"
                  onClick={() => handleChartTypeChange(ct.type)}
                  className={`rounded-lg border px-3 py-1.5 text-[11px] font-medium transition-all ${
                    chartType === ct.type
                      ? "border-blue-500 bg-blue-50 text-blue-700 shadow-sm"
                      : "border-slate-200 text-slate-600 hover:border-blue-300"
                  }`}
                >
                  {ct.icon} {ct.label}
                </button>
              ))}
            </div>
          </div>

          {/* Chart Subtype (if applicable) */}
          {currentChartDef && currentChartDef.subtypes.length > 0 && (
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-slate-600">
                {chartType === "bar" ? "Bar Style" : chartType === "line" ? "Line Style" : chartType === "area" ? "Area Style" : chartType === "pie" ? "Pie Style" : "Combo Style"}
              </label>
              <div className="flex flex-wrap gap-1.5">
                {currentChartDef.subtypes.map((st) => (
                  <button
                    key={st.value}
                    type="button"
                    onClick={() => setChartSubtype(st.value as ChartSubtype)}
                    className={`rounded-md border px-2.5 py-1 text-[10px] font-medium ${
                      chartSubtype === st.value
                        ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                        : "border-slate-200 text-slate-500 hover:border-indigo-300"
                    }`}
                  >
                    {st.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Data Source */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-slate-600">Data Source</label>
            <select
              className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
              value={`${sourceKind}:${sourceId}`}
              onChange={(e) => {
                const [kind, ...rest] = e.target.value.split(":");
                const id = rest.join(":");
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

          {/* Axis & Aggregation */}
          <fieldset className="rounded-lg border border-slate-100 p-3">
            <legend className="px-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Axis & Aggregation</legend>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-[10px] font-semibold text-slate-600">X Axis (Category / Dimension)</label>
                {columns.length > 0 ? (
                  <select
                    className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
                    value={xColumn}
                    onChange={(e) => {
                      setXColumn(e.target.value);
                      const ct = columns.find((c) => c.name === e.target.value)?.type;
                      if (ct === "date") setDateGranularity("month");
                      else setDateGranularity("");
                    }}
                  >
                    <option value="">Select column...</option>
                    {columns.map((c) => (
                      <option key={c.name} value={c.name}>{c.name} ({c.type})</option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
                    value={xColumn}
                    onChange={(e) => setXColumn(e.target.value)}
                    placeholder="Column name (e.g. region)"
                  />
                )}
              </div>
              <div>
                <label className="mb-1 block text-[10px] font-semibold text-slate-600">Y Axis (Measure / Value)</label>
                {columns.length > 0 ? (
                  <select
                    className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
                    value={yColumn}
                    onChange={(e) => setYColumn(e.target.value)}
                  >
                    <option value="">Select column...</option>
                    {numericColumns.map((c) => (
                      <option key={c.name} value={c.name}>{c.name}</option>
                    ))}
                    {/* For COUNT, allow any column */}
                    {stringColumns.map((c) => (
                      <option key={c.name} value={c.name}>{c.name} (string)</option>
                    ))}
                    {dateColumns.map((c) => (
                      <option key={c.name} value={c.name}>{c.name} (date)</option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
                    value={yColumn}
                    onChange={(e) => setYColumn(e.target.value)}
                    placeholder="Column name (e.g. amount)"
                  />
                )}
              </div>
            </div>

            {/* Date Granularity (only when X is date) */}
            {xColumnType === "date" && (
              <div className="mt-3">
                <label className="mb-1 block text-[10px] font-semibold text-slate-600">Date Granularity</label>
                <div className="flex gap-1">
                  {GRANULARITIES.map((g) => (
                    <button
                      key={g}
                      type="button"
                      onClick={() => setDateGranularity(g)}
                      className={`rounded-md border px-2 py-1 text-[10px] font-medium ${
                        dateGranularity === g
                          ? "border-amber-500 bg-amber-50 text-amber-700"
                          : "border-slate-200 text-slate-500 hover:border-amber-300"
                      }`}
                    >
                      {g}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Aggregation */}
            <div className="mt-3">
              <label className="mb-1 block text-[10px] font-semibold text-slate-600">Aggregation</label>
              <div className="flex gap-1">
                {AGGREGATIONS.map((a) => (
                  <button
                    key={a}
                    type="button"
                    onClick={() => setAggregation(a)}
                    className={`rounded-md border px-2.5 py-1 text-[10px] font-bold uppercase ${
                      aggregation === a
                        ? "border-sky-500 bg-sky-50 text-sky-700"
                        : "border-slate-200 text-slate-500 hover:border-sky-300"
                    }`}
                  >
                    {a}
                  </button>
                ))}
              </div>
            </div>

            {/* Group By */}
            <div className="mt-3">
              <label className="mb-1 block text-[10px] font-semibold text-slate-600">Group By / Color By (optional)</label>
              {columns.length > 0 ? (
                <select
                  className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
                  value={groupByColumn}
                  onChange={(e) => setGroupByColumn(e.target.value)}
                >
                  <option value="">None — single series</option>
                  {stringColumns.map((c) => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>
              ) : (
                <input
                  className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
                  value={groupByColumn}
                  onChange={(e) => setGroupByColumn(e.target.value)}
                  placeholder="Optional (e.g. category)"
                />
              )}
              <p className="mt-0.5 text-[9px] text-slate-400">Creates multiple series/bars/slices colored by this dimension</p>
            </div>

            {/* Combo chart Y2 axis */}
            {chartType === "combo" && (
              <div className="mt-3 rounded-md border border-dashed border-indigo-200 bg-indigo-50/30 p-2">
                <label className="mb-1 block text-[10px] font-semibold text-indigo-600">Secondary Y Axis (Line Overlay)</label>
                <div className="grid grid-cols-2 gap-2">
                  <select
                    className="rounded-md border border-slate-200 px-2 py-1 text-[10px] outline-none focus:border-blue-500"
                    value={y2Column}
                    onChange={(e) => setY2Column(e.target.value)}
                  >
                    <option value="">Select column...</option>
                    {columns.map((c) => (
                      <option key={c.name} value={c.name}>{c.name}</option>
                    ))}
                  </select>
                  <select
                    className="rounded-md border border-slate-200 px-2 py-1 text-[10px] outline-none focus:border-blue-500"
                    value={y2Aggregation}
                    onChange={(e) => setY2Aggregation(e.target.value as (typeof AGGREGATIONS)[number])}
                  >
                    {AGGREGATIONS.map((a) => (
                      <option key={a} value={a}>{a.toUpperCase()}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}
          </fieldset>

          {/* Sort & Limit */}
          <fieldset className="rounded-lg border border-slate-100 p-3">
            <legend className="px-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Sort & Limit</legend>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-[10px] font-semibold text-slate-600">Sort</label>
                <select
                  className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as "x_asc" | "x_desc" | "y_asc" | "y_desc")}
                >
                  {SORT_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
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
          </fieldset>

          {/* Widget Filters */}
          <fieldset className="rounded-lg border border-slate-100 p-3">
            <legend className="px-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Widget Filters</legend>
            {filters.map((f, idx) => (
              <div key={idx} className="mb-2 flex items-center gap-2">
                <select
                  className="rounded-md border border-slate-200 px-1.5 py-1 text-[10px]"
                  value={f.column}
                  onChange={(e) => updateFilter(idx, { column: e.target.value })}
                >
                  {columns.map((c) => (
                    <option key={c.name} value={c.name}>{c.name}</option>
                  ))}
                </select>
                <select
                  className="rounded-md border border-slate-200 px-1.5 py-1 text-[10px]"
                  value={f.operator}
                  onChange={(e) => updateFilter(idx, { operator: e.target.value })}
                >
                  {FILTER_OPERATORS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
                <input
                  className="flex-1 rounded-md border border-slate-200 px-2 py-1 text-[10px]"
                  value={String(f.value)}
                  onChange={(e) => updateFilter(idx, { value: e.target.value })}
                  placeholder="value"
                />
                <button type="button" onClick={() => removeFilter(idx)} className="text-[10px] text-red-500 hover:text-red-700">×</button>
              </div>
            ))}
            <button type="button" onClick={addFilter} className="text-[10px] font-medium text-blue-600 hover:text-blue-800">+ Add Filter</button>
          </fieldset>

          {/* Widget Size */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold text-slate-600">Widget Size</label>
            <div className="flex gap-1.5">
              {[
                { span: 3, label: "Small (1/4)" },
                { span: 6, label: "Medium (1/2)" },
                { span: 8, label: "Large (2/3)" },
                { span: 12, label: "Full" },
              ].map((s) => (
                <button
                  key={s.span}
                  type="button"
                  onClick={() => setColSpan(s.span)}
                  className={`rounded-md border px-2.5 py-1 text-[10px] font-medium ${
                    colSpan === s.span
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-slate-200 text-slate-500 hover:border-blue-300"
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right: Configuration Summary */}
        <div className="col-span-4">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <h4 className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">Configuration Summary</h4>
            <div className="space-y-1 text-[11px] text-slate-600">
              <div><span className="font-semibold">Chart:</span> {chartType}{chartSubtype ? ` (${chartSubtype.replace(/_/g, " ")})` : ""}</div>
              <div><span className="font-semibold">Source:</span> {sourceKind === "query" ? `Query #${sourceId}` : sourceId}</div>
              {xColumn && <div><span className="font-semibold">X:</span> {xColumn}</div>}
              {yColumn && (
                <div>
                  <span className="font-semibold">Y:</span>{" "}
                  <span className="font-bold text-sky-600">{aggregation.toUpperCase()}({yColumn})</span>
                </div>
              )}
              {chartType === "combo" && y2Column && (
                <div>
                  <span className="font-semibold">Y2:</span>{" "}
                  <span className="font-bold text-indigo-600">{y2Aggregation.toUpperCase()}({y2Column})</span>
                </div>
              )}
              {dateGranularity && <div><span className="font-semibold">Granularity:</span> {dateGranularity}</div>}
              {groupByColumn && <div><span className="font-semibold">Group:</span> {groupByColumn}</div>}
            </div>
          </div>

          {columns.length > 0 && (
            <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <h4 className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Detected Columns ({columns.length})
              </h4>
              <div className="flex flex-wrap gap-1">
                {columns.map((c) => (
                  <span
                    key={c.name}
                    className={`inline-block rounded px-1.5 py-0.5 text-[9px] font-semibold ${
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
        </div>
      </div>

      {/* Actions */}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium hover:bg-slate-50">
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={!canSave}
          className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
        >
          {editingWidget ? "Update Widget" : "Add Widget"}
        </button>
      </div>
    </div>
  );
}
