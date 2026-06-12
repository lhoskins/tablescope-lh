"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { WidgetConfig, WidgetType, ChartSubtype, WidgetFilter, ColumnInfo, VisualizationOptions, WidgetInteractions, WidgetClickAction, WidgetDateField } from "./types";
import type { QueryScope } from "@/types/query-scope";
import { WidgetRenderer } from "./WidgetRenderer";
import { ChartOptionsPanel } from "./ChartOptionsPanel";
import { getDefaultOptions } from "@/lib/visualizations/chartRegistry";

const CLICK_ACTIONS: { value: WidgetClickAction; label: string }[] = [
  { value: "none", label: "None" },
  { value: "cross_filter", label: "Filter dashboard" },
  { value: "drilldown", label: "Drill down to details" },
  { value: "drilldown_and_filter", label: "Filter + show details" },
];

// ── Chart type / subtype definitions ────────────────────────────────
type SubtypeDef = { value: ChartSubtype | ""; label: string };
type ChartTypeDef = { type: WidgetType; label: string; icon: string; subtypes: SubtypeDef[] };

const CHART_TYPES: ChartTypeDef[] = [
  {
    type: "bar", label: "Bar", icon: "\u{1F4CA}",
    subtypes: [
      { value: "column", label: "Column" },
      { value: "stacked_bar", label: "Stacked" },
      { value: "grouped_bar", label: "Grouped" },
      { value: "horizontal_bar", label: "Horizontal" },
      { value: "stacked_horizontal", label: "Stacked Horiz." },
    ],
  },
  {
    type: "line", label: "Line", icon: "\u{1F4C8}",
    subtypes: [
      { value: "", label: "Straight" },
      { value: "smooth_line", label: "Smooth" },
      { value: "step_line", label: "Step" },
    ],
  },
  {
    type: "area", label: "Area", icon: "\u{1F4C9}",
    subtypes: [
      { value: "", label: "Area" },
      { value: "stacked_area", label: "Stacked" },
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
    subtypes: [{ value: "bar_line", label: "Bar + Line" }],
  },
  {
    type: "scatter", label: "Scatter", icon: "\u{1F4A0}",
    subtypes: [
      { value: "", label: "Scatter" },
      { value: "bubble", label: "Bubble" },
    ],
  },
  {
    type: "radar", label: "Radar", icon: "\u{1F578}\u{FE0F}",
    subtypes: [
      { value: "", label: "Radar" },
      { value: "scorecard", label: "Scorecard" },
    ],
  },
  {
    type: "radial_bar", label: "Radial", icon: "\u{1F3AF}",
    subtypes: [
      { value: "", label: "Radial Bar" },
      { value: "multi_ring", label: "Multi-ring" },
    ],
  },
  { type: "treemap", label: "Treemap", icon: "\u{1F9E9}", subtypes: [] },
  { type: "funnel", label: "Funnel", icon: "\u{1FA9D}", subtypes: [] },
  { type: "sankey", label: "Sankey", icon: "\u{1F500}", subtypes: [] },
  { type: "kpi", label: "KPI", icon: "\u{1F522}", subtypes: [] },
  { type: "table", label: "Table", icon: "\u{1F4CB}", subtypes: [] },
];

const AGGREGATIONS = ["sum", "avg", "count", "min", "max"] as const;
const GRANULARITIES = ["day", "week", "month", "quarter", "year"] as const;
const SORT_OPTIONS = [
  { value: "x_asc", label: "X ascending" },
  { value: "x_desc", label: "X descending" },
  { value: "y_desc", label: "Y descending" },
  { value: "y_asc", label: "Y ascending" },
];
const FILTER_OPERATORS = [
  { value: "eq", label: "=" },
  { value: "neq", label: "!=" },
  { value: "gt", label: ">" },
  { value: "lt", label: "<" },
  { value: "gte", label: ">=" },
  { value: "lte", label: "<=" },
  { value: "in", label: "in" },
  { value: "contains", label: "contains" },
  { value: "begins_with", label: "begins with" },
  { value: "ends_with", label: "ends with" },
  { value: "like", label: "LIKE" },
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
  const [dateGranularity, setDateGranularity] = useState<string>(editingWidget?.dateGranularity ?? "");
  const [groupByColumn, setGroupByColumn] = useState(editingWidget?.groupByColumn ?? "");
  const [sortBy, setSortBy] = useState(editingWidget?.sortBy ?? "x_asc");
  const [limit, setLimit] = useState<string>(editingWidget?.limit?.toString() ?? "");
  const [filters, setFilters] = useState<WidgetFilter[]>(editingWidget?.filters ?? []);
  const [colSpan, setColSpan] = useState(editingWidget?.colSpan ?? 6);
  const [y2Column, setY2Column] = useState(editingWidget?.y2Column ?? "");
  const [y2Aggregation, setY2Aggregation] = useState<(typeof AGGREGATIONS)[number]>(editingWidget?.y2Aggregation ?? "avg");
  const [vizOptions, setVizOptions] = useState<VisualizationOptions>(
    editingWidget?.visualizationOptions ?? {}
  );
  const [interactions, setInteractions] = useState<WidgetInteractions>(
    editingWidget?.interactions ?? { enabled: false, clickAction: "none" }
  );
  const [dateFieldCfg, setDateFieldCfg] = useState<WidgetDateField>(
    editingWidget?.dateField ?? { enabled: false }
  );

  const viewName = sourceKind === "datasource" ? sourceId : "";
  const selectedQuery = sourceKind === "query" ? savedQueries.find((q) => q.id === Number(sourceId)) : null;

  // Fetch schema for datasource
  const { data: schemaData } = useQuery({
    queryKey: ["datasource-schema", projectId, viewName],
    queryFn: async () => {
      if (!viewName) return { columns: [] };
      return apiClient.get<{ columns: ColumnInfo[] }>(`/api/projects/${projectId}/dashboards/schema/${viewName}`);
    },
    enabled: !!viewName,
  });

  // Fetch columns from a query by executing with LIMIT 1
  const { data: queryColumnsData } = useQuery({
    queryKey: ["query-columns", projectId, selectedQuery?.id],
    queryFn: async () => {
      if (!selectedQuery) return { columns: [] as ColumnInfo[] };
      const sql = selectedQuery.sql_text;
      if (!sql) return { columns: [] as ColumnInfo[] };
      const limitedSql = sql.includes("LIMIT") ? sql : `${sql} LIMIT 1`;
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
          if (typeof val === "number") {
            type = "number";
          } else if (typeof val === "string" && /^\d{4}-\d{2}-\d{2}/.test(val)) {
            type = "date";
          } else if (typeof val === "string" && val !== "" && !isNaN(Number(val.replace(/[,$%]/g, "")))) {
            type = "number";
          }
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

  // Existing query scopes for the source query — used to offer a drilldown target.
  const { data: scopesData = [] } = useQuery({
    queryKey: ["query-scopes", selectedQuery?.id],
    queryFn: async () => {
      if (!selectedQuery) return [] as QueryScope[];
      return apiClient.get<QueryScope[]>(`/api/query-scopes?query_id=${selectedQuery.id}`);
    },
    enabled: sourceKind === "query" && !!selectedQuery,
  });

  const isChart = chartType !== "kpi" && chartType !== "table";
  const drilldownSelected =
    interactions.clickAction === "drilldown" || interactions.clickAction === "drilldown_and_filter";

  // Auto-detect X/Y for AI-generated widgets if columns loaded but names don't match
  useEffect(() => {
    if (columns.length > 0 && editingWidget) {
      if (xColumn && !columns.find((c) => c.name === xColumn)) {
        const match = columns.find((c) => c.name.toLowerCase() === xColumn.toLowerCase());
        if (match) setXColumn(match.name);
      }
      if (yColumn && !columns.find((c) => c.name === yColumn)) {
        const match = columns.find((c) => c.name.toLowerCase() === yColumn.toLowerCase());
        if (match) setYColumn(match.name);
      }
    }
  }, [columns, editingWidget, xColumn, yColumn]);

  // Auto-select first sensible columns
  useEffect(() => {
    if (columns.length > 0 && !editingWidget) {
      if (!xColumn) {
        const firstDate = dateColumns[0];
        const firstString = stringColumns[0];
        if (firstDate) { setXColumn(firstDate.name); setDateGranularity("month"); }
        else if (firstString) { setXColumn(firstString.name); }
      }
      if (!yColumn) {
        const firstNum = numericColumns[0];
        if (firstNum) setYColumn(firstNum.name);
        else if (columns.length > 0) setYColumn(columns[columns.length > 1 ? 1 : 0].name);
      }
    }
  }, [columns.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── LIVE PREVIEW: fetch data whenever config changes ──────────────
  const previewWidget = useMemo((): WidgetConfig => ({
    id: "preview",
    type: chartType,
    chartSubtype: chartSubtype || undefined,
    title: title || "Preview",
    dataSource: sourceKind === "query"
      ? { kind: "query", queryId: Number(sourceId) || 0 }
      : { kind: "datasource", viewName: sourceId },
    xColumn,
    xColumnType: xColumnType as "date" | "string" | "number" | undefined,
    dateGranularity: xColumnType === "date" && dateGranularity ? (dateGranularity as WidgetConfig["dateGranularity"]) : undefined,
    yColumn,
    aggregation,
    y2Column: (chartType === "combo" || chartType === "scatter") && y2Column ? y2Column : undefined,
    y2Aggregation: (chartType === "combo" || chartType === "scatter") && y2Column ? y2Aggregation : undefined,
    groupByColumn: groupByColumn || undefined,
    sortBy: sortBy as WidgetConfig["sortBy"],
    limit: limit ? parseInt(limit, 10) : undefined,
    filters,
    visualizationOptions: Object.keys(vizOptions).length > 0 ? vizOptions : undefined,
    interactions: interactions.enabled ? interactions : undefined,
    dateField: dateFieldCfg.enabled ? dateFieldCfg : undefined,
    colSpan,
    position: 0,
  }), [chartType, chartSubtype, title, sourceKind, sourceId, xColumn, xColumnType, dateGranularity, yColumn, aggregation, y2Column, y2Aggregation, groupByColumn, sortBy, limit, filters, vizOptions, interactions, dateFieldCfg, colSpan]);

  const canFetchPreview = !!sourceId && !!xColumn && !!yColumn;

  const { data: previewData } = useQuery({
    queryKey: ["widget-preview", projectId, sourceKind, sourceId, xColumn, yColumn, aggregation, dateGranularity, groupByColumn, sortBy, limit, JSON.stringify(filters)],
    queryFn: async () => {
      if (sourceKind === "datasource" && sourceId) {
        const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
          `/api/projects/${projectId}/dashboards/widget-query`,
          {
            view_name: sourceId,
            x_column: xColumn,
            y_column: yColumn,
            aggregation: aggregation ?? "sum",
            date_granularity: dateGranularity || null,
            group_by_column: groupByColumn || null,
            sort_by: sortBy ?? "x_asc",
            limit: limit ? parseInt(limit, 10) : null,
            filters: filters ?? [],
            global_filters: [],
          }
        );
        return resp.rows ?? [];
      }
      if (sourceKind === "query" && selectedQuery?.sql_text) {
        const tableMatch = selectedQuery.sql_text.match(/FROM\s+"?([A-Za-z0-9_]+)"?/i);
        const tableName = tableMatch ? tableMatch[1] : "dual";
        const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
          "/api/query/datasource",
          { tableName, sql: selectedQuery.sql_text, limit: 100, project_id: projectId }
        );
        return resp.rows ?? [];
      }
      return [];
    },
    enabled: canFetchPreview,
    staleTime: 5000,
  });

  const handleSave = useCallback(() => {
    if (!title.trim() || !xColumn || !yColumn) return;
    onSave({ ...previewWidget, id: editingWidget?.id ?? `w-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, position: editingWidget?.position ?? 0, gridW: editingWidget?.gridW, gridH: editingWidget?.gridH, gridX: editingWidget?.gridX, gridY: editingWidget?.gridY });
  }, [previewWidget, editingWidget, title, xColumn, yColumn, onSave]);

  const addFilter = () => { setFilters([...filters, { column: columns[0]?.name ?? "", operator: "eq", value: "" }]); };
  const removeFilter = (idx: number) => { setFilters(filters.filter((_, i) => i !== idx)); };
  const updateFilter = (idx: number, patch: Partial<WidgetFilter>) => { setFilters(filters.map((f, i) => (i === idx ? { ...f, ...patch } : f))); };

  const canSave = title.trim() && xColumn && yColumn && sourceId;

  const handleChartTypeChange = (type: WidgetType) => {
    setChartType(type);
    const def = CHART_TYPES.find((ct) => ct.type === type);
    if (def && def.subtypes.length > 0) setChartSubtype(def.subtypes[0].value as ChartSubtype);
    else setChartSubtype("");
    // Seed registry defaults for the newly selected chart type.
    setVizOptions(getDefaultOptions(type));
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-lg">
      {/* Panel Header */}
      <div className="flex items-center justify-between rounded-t-xl bg-slate-800 px-5 py-3">
        <h3 className="text-sm font-bold text-white">
          {editingWidget ? "Edit Widget" : "New Widget"}
        </h3>
        <div className="flex gap-2">
          <button onClick={onCancel} className="rounded-md border border-slate-600 px-3 py-1 text-xs font-medium text-slate-300 hover:bg-slate-700">
            Cancel
          </button>
          <button onClick={handleSave} disabled={!canSave} className="rounded-md bg-blue-500 px-3 py-1 text-xs font-bold text-white disabled:opacity-40 hover:bg-blue-600">
            {editingWidget ? "Update" : "Add to Dashboard"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-0">
        {/* Left: Config */}
        <div className="col-span-5 space-y-3 border-r border-slate-200 p-4 overflow-y-auto max-h-[600px]">
          {/* Title */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Title</label>
            <input className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-xs outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-200" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Monthly Revenue" />
          </div>

          {/* Chart Type */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Chart Type</label>
            <div className="flex flex-wrap gap-1">
              {CHART_TYPES.map((ct) => (
                <button key={ct.type} type="button" onClick={() => handleChartTypeChange(ct.type)}
                  className={`rounded-md border px-2 py-1 text-[10px] font-medium transition-all ${chartType === ct.type ? "border-blue-500 bg-blue-50 text-blue-700 shadow-sm" : "border-slate-200 text-slate-500 hover:border-blue-300"}`}>
                  {ct.icon} {ct.label}
                </button>
              ))}
            </div>
          </div>

          {/* Chart Subtype */}
          {currentChartDef && currentChartDef.subtypes.length > 0 && (
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Style</label>
              <div className="flex flex-wrap gap-1">
                {currentChartDef.subtypes.map((st) => (
                  <button key={st.value} type="button" onClick={() => setChartSubtype(st.value as ChartSubtype)}
                    className={`rounded-md border px-2 py-1 text-[10px] font-medium ${chartSubtype === st.value ? "border-indigo-500 bg-indigo-50 text-indigo-700" : "border-slate-200 text-slate-400 hover:border-indigo-300"}`}>
                    {st.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Data Source */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Data Source</label>
            <select className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px] outline-none focus:border-blue-500"
              value={`${sourceKind}:${sourceId}`}
              onChange={(e) => { const [kind, ...rest] = e.target.value.split(":"); setSourceKind(kind as "datasource" | "query"); setSourceId(rest.join(":")); setXColumn(""); setYColumn(""); setGroupByColumn(""); }}>
              <option value="datasource:">Select...</option>
              {datasources.map((ds) => (<option key={ds.viewName} value={`datasource:${ds.viewName}`}>DS: {ds.fileName}</option>))}
              {savedQueries.map((q) => (<option key={q.id} value={`query:${q.id}`}>Query: {q.name}</option>))}
            </select>
          </div>

          {/* X / Y Columns */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">X Axis</label>
              {columns.length > 0 ? (
                <select className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px]" value={xColumn}
                  onChange={(e) => { setXColumn(e.target.value); const ct = columns.find((c) => c.name === e.target.value)?.type; if (ct === "date") setDateGranularity("month"); else setDateGranularity(""); }}>
                  <option value="">Select...</option>
                  {columns.map((c) => (<option key={c.name} value={c.name}>{c.name} ({c.type})</option>))}
                </select>
              ) : (
                <input className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px]" value={xColumn} onChange={(e) => setXColumn(e.target.value)} placeholder="region" />
              )}
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Y Axis</label>
              {columns.length > 0 ? (
                <select className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px]" value={yColumn} onChange={(e) => setYColumn(e.target.value)}>
                  <option value="">Select...</option>
                  {columns.map((c) => (<option key={c.name} value={c.name}>{c.name} ({c.type})</option>))}
                </select>
              ) : (
                <input className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px]" value={yColumn} onChange={(e) => setYColumn(e.target.value)} placeholder="amount" />
              )}
            </div>
          </div>

          {/* Per-type field-role hints */}
          {chartType === "sankey" && (
            <p className="rounded-md bg-amber-50 px-2 py-1 text-[10px] text-amber-700">
              Sankey: X = source, <strong>Group By</strong> = target, Y = flow value.
            </p>
          )}
          {chartType === "scatter" && (
            <p className="rounded-md bg-sky-50 px-2 py-1 text-[10px] text-sky-700">
              Scatter: X &amp; Y are numeric measures. For a bubble, set Secondary Y as the size (Z) and enable Bubble in Chart Options.
            </p>
          )}
          {(chartType === "radar" || chartType === "radial_bar" || chartType === "treemap" || chartType === "funnel") && (
            <p className="rounded-md bg-violet-50 px-2 py-1 text-[10px] text-violet-700">
              X = category/label, Y = value{chartType === "radar" ? ". Use Group By to compare multiple entities." : "."}
            </p>
          )}

          {/* Date granularity */}
          {xColumnType === "date" && (
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Date Granularity</label>
              <div className="flex gap-1">
                {GRANULARITIES.map((g) => (
                  <button key={g} type="button" onClick={() => setDateGranularity(g)}
                    className={`rounded-md border px-2 py-0.5 text-[10px] font-medium ${dateGranularity === g ? "border-amber-500 bg-amber-50 text-amber-700" : "border-slate-200 text-slate-400"}`}>
                    {g}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Aggregation */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Aggregation</label>
            <div className="flex gap-1">
              {AGGREGATIONS.map((a) => (
                <button key={a} type="button" onClick={() => setAggregation(a)}
                  className={`rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase ${aggregation === a ? "border-sky-500 bg-sky-50 text-sky-700" : "border-slate-200 text-slate-400"}`}>
                  {a}
                </button>
              ))}
            </div>
          </div>

          {/* Group By */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Group By (optional)</label>
            {columns.length > 0 ? (
              <select className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px]" value={groupByColumn} onChange={(e) => setGroupByColumn(e.target.value)}>
                <option value="">None</option>
                {stringColumns.map((c) => (<option key={c.name} value={c.name}>{c.name}</option>))}
              </select>
            ) : (
              <input className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px]" value={groupByColumn} onChange={(e) => setGroupByColumn(e.target.value)} placeholder="category" />
            )}
          </div>

          {/* Sort & Limit */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Sort</label>
              <select className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px]" value={sortBy} onChange={(e) => setSortBy(e.target.value as WidgetConfig["sortBy"])}>
                {SORT_OPTIONS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Limit</label>
              <select className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-[11px]" value={limit} onChange={(e) => setLimit(e.target.value)}>
                <option value="">All</option>
                <option value="5">Top 5</option><option value="10">Top 10</option><option value="20">Top 20</option><option value="50">Top 50</option>
              </select>
            </div>
          </div>

          {/* Combo Y2 / Scatter Z */}
          {(chartType === "combo" || chartType === "scatter") && (
            <div className="rounded-md border border-dashed border-indigo-200 bg-indigo-50/30 p-2">
              <label className="mb-1 block text-[10px] font-semibold text-indigo-600">
                {chartType === "scatter" ? "Bubble size (Z, optional)" : "Secondary Y (Line)"}
              </label>
              <div className="grid grid-cols-2 gap-2">
                <select className="rounded-md border border-slate-200 px-2 py-1 text-[10px]" value={y2Column} onChange={(e) => setY2Column(e.target.value)}>
                  <option value="">Select...</option>
                  {columns.map((c) => (<option key={c.name} value={c.name}>{c.name}</option>))}
                </select>
                <select className="rounded-md border border-slate-200 px-2 py-1 text-[10px]" value={y2Aggregation} onChange={(e) => setY2Aggregation(e.target.value as (typeof AGGREGATIONS)[number])}>
                  {AGGREGATIONS.map((a) => (<option key={a} value={a}>{a.toUpperCase()}</option>))}
                </select>
              </div>
            </div>
          )}

          {/* Filters */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Filters</label>
            {filters.map((f, idx) => (
              <div key={idx} className="mb-1 flex items-center gap-1">
                <select className="rounded border border-slate-200 px-1 py-0.5 text-[10px]" value={f.column} onChange={(e) => updateFilter(idx, { column: e.target.value })}>
                  {columns.map((c) => (<option key={c.name} value={c.name}>{c.name}</option>))}
                </select>
                <select className="rounded border border-slate-200 px-1 py-0.5 text-[10px]" value={f.operator} onChange={(e) => updateFilter(idx, { operator: e.target.value })}>
                  {FILTER_OPERATORS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                </select>
                <input className="flex-1 rounded border border-slate-200 px-1 py-0.5 text-[10px]" value={String(f.value)} onChange={(e) => updateFilter(idx, { value: e.target.value })} />
                <button type="button" onClick={() => removeFilter(idx)} className="text-red-400 hover:text-red-600">x</button>
              </div>
            ))}
            <button type="button" onClick={addFilter} className="text-[10px] font-medium text-blue-500 hover:text-blue-700">+ Filter</button>
          </div>

          {/* Size */}
          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Size</label>
            <div className="flex gap-1">
              {[{ span: 3, label: "S" }, { span: 6, label: "M" }, { span: 8, label: "L" }, { span: 12, label: "Full" }].map((s) => (
                <button key={s.span} type="button" onClick={() => setColSpan(s.span)}
                  className={`rounded-md border px-2 py-0.5 text-[10px] font-medium ${colSpan === s.span ? "border-blue-500 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-400"}`}>
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          {/* Chart Options (registry-driven) */}
          {isChart && (
            <div className="border-t border-slate-100 pt-3">
              <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">Chart Options</label>
              <ChartOptionsPanel chartType={chartType} value={vizOptions} onChange={setVizOptions} />
            </div>
          )}

          {/* Interactions (drilldown / cross-filter) */}
          {isChart && (
            <div className="border-t border-slate-100 pt-3">
              <label className="mb-1.5 flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Interactions
                <label className="flex items-center gap-1 text-[10px] font-medium normal-case text-slate-600">
                  <input
                    type="checkbox"
                    checked={!!interactions.enabled}
                    onChange={(e) => setInteractions((p) => ({ ...p, enabled: e.target.checked, clickAction: p.clickAction && p.clickAction !== "none" ? p.clickAction : "cross_filter", applyTo: "dashboard" }))}
                  />
                  Enable click
                </label>
              </label>
              {interactions.enabled && (
                <div className="space-y-2">
                  <div>
                    <label className="mb-1 block text-[10px] font-medium text-slate-500">Click action</label>
                    <select
                      className="w-full rounded border border-slate-200 px-2 py-1 text-[11px]"
                      value={interactions.clickAction ?? "none"}
                      onChange={(e) => setInteractions((p) => ({ ...p, clickAction: e.target.value as WidgetClickAction }))}
                    >
                      {CLICK_ACTIONS.map((a) => (<option key={a.value} value={a.value}>{a.label}</option>))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] font-medium text-slate-500">Source field</label>
                    <select
                      className="w-full rounded border border-slate-200 px-2 py-1 text-[11px]"
                      value={interactions.sourceField ?? ""}
                      onChange={(e) => setInteractions((p) => ({ ...p, sourceField: e.target.value || undefined }))}
                    >
                      <option value="">X axis ({xColumn || "—"})</option>
                      {columns.map((c) => (<option key={c.name} value={c.name}>{c.name}</option>))}
                    </select>
                  </div>
                  {drilldownSelected && (
                    sourceKind === "query" ? (
                      <div>
                        <label className="mb-1 block text-[10px] font-medium text-slate-500">Drilldown scope</label>
                        <select
                          className="w-full rounded border border-slate-200 px-2 py-1 text-[11px]"
                          value={interactions.scopeId ?? ""}
                          onChange={(e) => setInteractions((p) => ({ ...p, scopeId: e.target.value ? Number(e.target.value) : undefined }))}
                        >
                          <option value="">Auto (match clicked field)</option>
                          {scopesData.map((s) => (
                            <option key={s.id} value={s.id}>{s.source_field} → query #{s.target_query_id}.{s.target_field}</option>
                          ))}
                        </select>
                        {scopesData.length === 0 && (
                          <p className="mt-1 text-[10px] text-amber-600">No scopes on this query. Create one in the Scopes tab.</p>
                        )}
                      </div>
                    ) : (
                      <p className="text-[10px] text-amber-600">Drilldown uses query scopes — set this widget&apos;s data source to a saved query to enable it.</p>
                    )
                  )}
                </div>
              )}
            </div>
          )}

          {/* Date field mapping (for dashboard date-range filter) */}
          {isChart && (
            <div className="border-t border-slate-100 pt-3">
              <label className="mb-1.5 flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Date Filter
                <label className="flex items-center gap-1 text-[10px] font-medium normal-case text-slate-600">
                  <input
                    type="checkbox"
                    checked={!!dateFieldCfg.enabled}
                    onChange={(e) => setDateFieldCfg((p) => ({ ...p, enabled: e.target.checked, field: p.field || dateColumns[0]?.name || xColumn }))}
                  />
                  Respond to date range
                </label>
              </label>
              {dateFieldCfg.enabled && (
                <div>
                  <label className="mb-1 block text-[10px] font-medium text-slate-500">Date field</label>
                  <select
                    className="w-full rounded border border-slate-200 px-2 py-1 text-[11px]"
                    value={dateFieldCfg.field ?? ""}
                    onChange={(e) => setDateFieldCfg((p) => ({ ...p, field: e.target.value || undefined }))}
                  >
                    <option value="">Select a date column…</option>
                    {(dateColumns.length > 0 ? dateColumns : columns).map((c) => (
                      <option key={c.name} value={c.name}>{c.name}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Live Preview */}
        <div className="col-span-7 flex flex-col bg-slate-50 p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Live Preview</span>
            {canFetchPreview && previewData && (
              <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-[9px] font-semibold text-emerald-600">
                Data loaded: {previewData.length} rows
              </span>
            )}
          </div>
          <div className="flex-1 min-h-[320px]">
            {canFetchPreview ? (
              <WidgetRenderer widget={previewWidget} data={previewData ?? []} />
            ) : (
              <div className="flex h-full items-center justify-center rounded-lg border-2 border-dashed border-slate-200 text-xs text-slate-400">
                Select a data source and columns to see a live preview
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
