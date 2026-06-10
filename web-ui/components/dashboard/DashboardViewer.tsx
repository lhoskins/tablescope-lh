"use client";

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ResponsiveGridLayout, type Layout, type LayoutItem } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import { apiClient } from "@/lib/api-client";
import type { Dashboard, WidgetConfig, DashboardConfig, DashboardFilter, ColumnInfo, WidgetFilter } from "./types";
import { WidgetRenderer } from "./WidgetRenderer";
import { WidgetConfigPanel } from "./WidgetConfigPanel";
import { FilterBar } from "./FilterBar";

type SavedQuery = { id: number; name: string; sql_text: string | null };
type Datasource = { viewName: string; fileName: string };

type Props = {
  dashboard: Dashboard;
  projectId: number;
  savedQueries: SavedQuery[];
  datasources: Datasource[];
  onBack: () => void;
};

export function DashboardViewer({ dashboard, projectId, savedQueries, datasources, onBack }: Props) {
  const queryClient = useQueryClient();
  const widgets = useMemo(() => dashboard.config?.widgets ?? [], [dashboard.config?.widgets]);
  const globalFilters = useMemo(() => dashboard.config?.globalFilters ?? [], [dashboard.config?.globalFilters]);

  const [widgetData, setWidgetData] = useState<Record<string, Array<Record<string, unknown>>>>({});
  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [dashboardStatus, setDashboardStatus] = useState(dashboard.status);

  const toggleStatusMutation = useMutation({
    mutationFn: async () => {
      const newStatus = dashboardStatus === "published" ? "draft" : "published";
      await apiClient.put(`/api/projects/${projectId}/dashboards/${dashboard.id}`, { status: newStatus });
      return newStatus;
    },
    onSuccess: (newStatus: string) => {
      setDashboardStatus(newStatus);
      queryClient.invalidateQueries({ queryKey: ["dashboards", projectId] });
    },
  });
  const [editingWidget, setEditingWidget] = useState<WidgetConfig | null>(null);

  // Collect query IDs referenced by widgets that aren't in the provided savedQueries
  const missingQueryIds = useMemo(() => {
    const ids: number[] = [];
    widgets.forEach((w) => {
      if (w.dataSource?.kind === "query" && w.dataSource.queryId) {
        if (!savedQueries.find((q) => q.id === w.dataSource.queryId)) {
          ids.push(w.dataSource.queryId);
        }
      }
    });
    return [...new Set(ids)];
  }, [widgets, savedQueries]);

  // Fetch missing queries (e.g. AI-generated ones not yet in parent's cache)
  const { data: fetchedQueries = [] } = useQuery({
    queryKey: ["missing-queries", projectId, missingQueryIds],
    queryFn: () =>
      apiClient.get<SavedQuery[]>(`/api/projects/${projectId}/queries`),
    enabled: missingQueryIds.length > 0,
  });

  // Merged list of all queries available to widgets
  const allQueries = useMemo(() => {
    const map = new Map<number, SavedQuery>();
    savedQueries.forEach((q) => map.set(q.id, q));
    fetchedQueries.forEach((q: SavedQuery) => map.set(q.id, q));
    return Array.from(map.values());
  }, [savedQueries, fetchedQueries]);

  const viewNames = useMemo(() => {
    const names = new Set<string>();
    widgets.forEach((w) => {
      if (w.dataSource?.kind === "datasource" && w.dataSource.viewName) {
        names.add(w.dataSource.viewName);
      }
    });
    return Array.from(names);
  }, [widgets]);

  const { data: schemaData } = useQuery({
    queryKey: ["datasource-schema", projectId, viewNames[0]],
    queryFn: async () => {
      if (!viewNames[0]) return { columns: [] };
      return apiClient.get<{ columns: ColumnInfo[] }>(
        `/api/projects/${projectId}/dashboards/schema/${viewNames[0]}`
      );
    },
    enabled: viewNames.length > 0,
  });
  const allColumns: ColumnInfo[] = schemaData?.columns ?? [];

  const updateMutation = useMutation({
    mutationFn: (body: { config: DashboardConfig }) =>
      apiClient.put(`/api/projects/${projectId}/dashboards/${dashboard.id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-dashboards", projectId] });
    },
  });

  const globalFiltersForApi = useCallback((): WidgetFilter[] => {
    const result: WidgetFilter[] = [];
    for (const f of globalFilters) {
      if (f.filterType === "date_range") {
        const val = f.value as { from?: string; to?: string } | null;
        if (val?.from) result.push({ column: f.column, operator: "gte", value: val.from });
        if (val?.to) result.push({ column: f.column, operator: "lte", value: val.to });
      } else if (f.filterType === "numeric_range") {
        const val = f.value as { min?: string; max?: string } | null;
        if (val?.min) result.push({ column: f.column, operator: "gte", value: Number(val.min) });
        if (val?.max) result.push({ column: f.column, operator: "lte", value: Number(val.max) });
      } else if (f.filterType === "multi_select") {
        const val = f.value as string[] | null;
        if (val && val.length > 0) result.push({ column: f.column, operator: "in", value: val });
      } else if (f.filterType === "text") {
        const val = f.value as string | null;
        if (val) result.push({ column: f.column, operator: "contains", value: val });
      }
    }
    return result;
  }, [globalFilters]);

  const fetchWidgetData = useCallback(async (w: WidgetConfig) => {
    try {
      if (w.xColumn && w.yColumn && w.dataSource.kind === "datasource" && w.dataSource.viewName) {
        const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[]; sql: string }>(
          `/api/projects/${projectId}/dashboards/widget-query`,
          {
            view_name: w.dataSource.viewName,
            x_column: w.xColumn,
            y_column: w.yColumn,
            aggregation: w.aggregation ?? "sum",
            date_granularity: w.dateGranularity ?? null,
            group_by_column: w.groupByColumn ?? null,
            sort_by: w.sortBy ?? "x_asc",
            limit: w.limit ?? null,
            filters: w.filters ?? [],
            global_filters: globalFiltersForApi(),
          }
        );
        return resp.rows ?? [];
      }
      if (w.dataSource.kind === "datasource" && w.dataSource.viewName) {
        const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
          "/api/query/datasource",
          { tableName: w.dataSource.viewName, limit: 100, project_id: projectId }
        );
        return resp.rows ?? [];
      }
      if (w.dataSource?.kind === "query" && w.dataSource.queryId) {
        const query = allQueries.find((q) => q.id === w.dataSource.queryId);
        if (query?.sql_text) {
          const tableMatch = query.sql_text.match(/FROM\s+"?([A-Za-z0-9_]+)"?/i);
          const tableName = tableMatch ? tableMatch[1] : "dual";
          const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
            "/api/query/datasource",
            { tableName, sql: query.sql_text, limit: 500, project_id: projectId }
          );
          return resp.rows ?? [];
        }
      }
    } catch {
      /* widget shows "No data" */
    }
    return [];
  }, [allQueries, projectId, globalFiltersForApi]);

  useEffect(() => {
    const loadAll = async () => {
      const entries = await Promise.all(
        widgets.map(async (w) => {
          const rows = await fetchWidgetData(w);
          return [w.id, rows] as const;
        }),
      );
      const results: Record<string, Array<Record<string, unknown>>> = {};
      for (const [id, rows] of entries) results[id] = rows;
      setWidgetData(results);
    };
    if (widgets.length > 0) loadAll();
  }, [widgets, fetchWidgetData]);

  const handleSaveWidget = (widget: WidgetConfig) => {
    let updatedWidgets: WidgetConfig[];
    if (editingWidget) {
      updatedWidgets = widgets.map((w) => (w.id === editingWidget.id ? { ...widget, position: w.position, gridX: w.gridX, gridY: w.gridY, gridW: widget.gridW ?? w.gridW, gridH: widget.gridH ?? w.gridH } : w));
    } else {
      updatedWidgets = [...widgets, { ...widget, position: widgets.length }];
    }
    updateMutation.mutate({ config: { widgets: updatedWidgets, globalFilters } });
    setShowConfigPanel(false);
    setEditingWidget(null);
  };

  const handleDeleteWidget = (id: string) => {
    const updatedWidgets = widgets.filter((w) => w.id !== id);
    updateMutation.mutate({ config: { widgets: updatedWidgets, globalFilters } });
  };

  const handleEditWidget = (w: WidgetConfig) => {
    setEditingWidget(w);
    setShowConfigPanel(true);
  };

  const handleFiltersChange = (newFilters: DashboardFilter[]) => {
    updateMutation.mutate({ config: { widgets, globalFilters: newFilters } });
  };

  // ── react-grid-layout ────────────────────────────────────────────
  const colSpanToGridW = (span: number) => Math.min(12, Math.max(2, span));

  const layoutRef = useRef<LayoutItem[]>([]);
  const layouts = useMemo(() => {
    const lg: LayoutItem[] = widgets.map((w, idx) => ({
      i: w.id,
      x: w.gridX ?? ((idx * (w.colSpan || 6)) % 12),
      y: w.gridY ?? Math.floor((idx * (w.colSpan || 6)) / 12) * 4,
      w: w.gridW ?? colSpanToGridW(w.colSpan || 6),
      h: w.gridH ?? (w.type === "kpi" ? 2 : 4),
      minW: 2,
      minH: 2,
    }));
    layoutRef.current = lg;
    return { lg };
  }, [widgets]);

  const handleLayoutChange = useCallback((layout: Layout, _layouts: Record<string, Layout>) => {
    const prev = layoutRef.current;
    const changed = layout.some((l) => {
      const p = prev.find((pl) => pl.i === l.i);
      return p && (p.x !== l.x || p.y !== l.y || p.w !== l.w || p.h !== l.h);
    });
    if (!changed) return;
    layoutRef.current = [...layout];
    const updatedWidgets = widgets.map((w) => {
      const l = layout.find((li) => li.i === w.id);
      if (!l) return w;
      return { ...w, gridX: l.x, gridY: l.y, gridW: l.w, gridH: l.h };
    });
    updateMutation.mutate({ config: { widgets: updatedWidgets, globalFilters } });
  }, [widgets, globalFilters, updateMutation]);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* ── Looker-style dark toolbar ────────────────────────────── */}
      <div className="rounded-t-xl bg-slate-800 px-5 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={onBack} className="flex items-center gap-1 text-[11px] font-medium text-slate-400 hover:text-white transition-colors">
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
              Dashboards
            </button>
            <div className="h-4 w-px bg-slate-600" />
            <h2 className="text-sm font-bold text-white">{dashboard.name}</h2>
            {dashboardStatus !== "published" && (
              <span className="rounded-full bg-amber-900/50 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-amber-300">
                {dashboardStatus}
              </span>
            )}
            <button
              onClick={() => toggleStatusMutation.mutate()}
              disabled={toggleStatusMutation.isPending}
              className={`rounded-md px-2.5 py-1 text-[10px] font-bold transition-colors ${
                dashboardStatus === "published"
                  ? "border border-slate-600 text-slate-300 hover:bg-slate-700"
                  : "bg-emerald-600 text-white hover:bg-emerald-700"
              } disabled:opacity-50`}
            >
              {toggleStatusMutation.isPending
                ? "Updating..."
                : dashboardStatus === "published"
                  ? "Unpublish"
                  : "Publish"}
            </button>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500">
              {widgets.length} widget{widgets.length !== 1 ? "s" : ""}
            </span>
            <div className="h-4 w-px bg-slate-600" />
            <button
              onClick={() => {
                const loadAll = async () => {
                  const results: Record<string, Array<Record<string, unknown>>> = {};
                  for (const w of widgets) results[w.id] = await fetchWidgetData(w);
                  setWidgetData(results);
                };
                loadAll();
              }}
              className="flex items-center gap-1 rounded-md border border-slate-600 px-2.5 py-1 text-[10px] font-medium text-slate-300 hover:bg-slate-700 transition-colors"
            >
              <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
              Refresh
            </button>
            <button
              onClick={() => { setEditingWidget(null); setShowConfigPanel(true); }}
              className="flex items-center gap-1 rounded-md bg-blue-500 px-2.5 py-1 text-[10px] font-bold text-white hover:bg-blue-600 transition-colors"
            >
              <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" /></svg>
              Add Widget
            </button>
          </div>
        </div>
      </div>

      {/* ── Filter Bar ───────────────────────────────────────────── */}
      <div className="border-b border-slate-200 bg-white px-5 py-2">
        <FilterBar filters={globalFilters} columns={allColumns} onChange={handleFiltersChange} />
      </div>

      {/* ── Widget Config Panel (slide-down) ──────────────────────── */}
      {showConfigPanel && (
        <div className="mx-4 mt-4">
          <WidgetConfigPanel
            projectId={projectId}
            savedQueries={savedQueries}
            datasources={datasources}
            editingWidget={editingWidget}
            onSave={handleSaveWidget}
            onCancel={() => { setShowConfigPanel(false); setEditingWidget(null); }}
          />
        </div>
      )}

      {/* ── Widget Grid ──────────────────────────────────────────── */}
      <div className="px-4 py-4">
        {widgets.length === 0 && !showConfigPanel ? (
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-white py-20">
            <svg className="mb-3 h-12 w-12 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
            <p className="text-sm font-semibold text-slate-600">No widgets yet</p>
            <p className="mt-1 text-xs text-slate-400">Click &quot;+ Add Widget&quot; to start building your dashboard</p>
          </div>
        ) : widgets.length > 0 ? (
          <ResponsiveGridLayout
            className="layout"
            layouts={layouts}
            breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
            cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
            rowHeight={80}
            onLayoutChange={handleLayoutChange}
            dragConfig={{ enabled: true, handle: ".widget-drag-handle", bounded: false, threshold: 3 }}
            resizeConfig={{ enabled: true }}
            width={1200}
          >
            {widgets.map((w) => (
              <div key={w.id}>
                <div className="h-full rounded-lg border border-slate-200 bg-white shadow-sm hover:shadow-md transition-shadow overflow-hidden">
                  {/* Widget header — drag handle + metadata badges */}
                  <div className="widget-drag-handle flex items-center justify-between border-b border-slate-100 bg-white px-3 py-2 cursor-grab active:cursor-grabbing">
                    <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <svg className="h-3 w-3 flex-shrink-0 text-slate-300" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="5" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="12" cy="19" r="2"/></svg>
                        <h4 className="truncate text-xs font-bold text-slate-800">{w.title || "Untitled"}</h4>
                      </div>
                      {w.aggregation && w.yColumn && (
                        <div className="flex flex-wrap items-center gap-1 pl-5">
                          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[8px] font-bold uppercase text-blue-600">
                            {w.aggregation}({w.yColumn})
                          </span>
                          {w.xColumn && (
                            <>
                              <span className="text-[8px] text-slate-400">grouped by</span>
                              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[8px] font-bold text-emerald-700">
                                {w.xColumn}
                              </span>
                            </>
                          )}
                          {w.groupByColumn && (
                            <>
                              <span className="text-[8px] text-slate-400">color by</span>
                              <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[8px] font-bold text-violet-700">
                                {w.groupByColumn}
                              </span>
                            </>
                          )}
                          {w.dateGranularity && (
                            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[8px] font-bold uppercase text-amber-700">
                              {w.dateGranularity}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-0.5 flex-shrink-0 ml-2">
                      <button onClick={() => handleEditWidget(w)} title="Edit" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors">
                        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                      </button>
                      <button onClick={() => handleDeleteWidget(w.id)} title="Delete" className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-500 transition-colors">
                        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                      </button>
                    </div>
                  </div>
                  {/* Chart */}
                  <div className="p-3 overflow-hidden" style={{ height: "calc(100% - 52px)" }}>
                    <WidgetRenderer widget={w} data={widgetData[w.id] ?? []} />
                  </div>
                </div>
              </div>
            ))}
          </ResponsiveGridLayout>
        ) : null}
      </div>
    </div>
  );
}
