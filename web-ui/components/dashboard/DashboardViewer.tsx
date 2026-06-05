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

// react-grid-layout v2 does not export WidthProvider; Responsive handles width
// automatically via a container ref.

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
  const [editingWidget, setEditingWidget] = useState<WidgetConfig | null>(null);

  const viewNames = useMemo(() => {
    const names = new Set<string>();
    widgets.forEach((w) => {
      if (w.dataSource.kind === "datasource" && w.dataSource.viewName) {
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
      // Widget-query endpoint for datasource with aggregation config
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
      // Legacy fallback: raw datasource query
      if (w.dataSource.kind === "datasource" && w.dataSource.viewName) {
        const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
          "/api/query/datasource",
          { tableName: w.dataSource.viewName, limit: 100, project_id: projectId }
        );
        return resp.rows ?? [];
      }
      // Query-based widget: execute the saved query's SQL via the datasource endpoint
      if (w.dataSource.kind === "query" && w.dataSource.queryId) {
        const query = savedQueries.find((q) => q.id === w.dataSource.queryId);
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
      // swallow — widget shows "No data available"
    }
    return [];
  }, [savedQueries, projectId, globalFiltersForApi]);

  useEffect(() => {
    const loadAll = async () => {
      const results: Record<string, Array<Record<string, unknown>>> = {};
      for (const w of widgets) {
        results[w.id] = await fetchWidgetData(w);
      }
      setWidgetData(results);
    };
    if (widgets.length > 0) {
      loadAll();
    }
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
    <div>
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div>
          <button onClick={onBack} className="mb-1 text-xs font-medium text-blue-600 hover:underline">
            &larr; Back to Dashboards
          </button>
          <h2 className="text-lg font-bold text-slate-900">{dashboard.name}</h2>
          <p className="text-[11px] text-slate-500">
            {widgets.length} widget{widgets.length !== 1 ? "s" : ""} &middot; Status:{" "}
            <span className="font-medium">{dashboard.status}</span>
            &nbsp;&middot;&nbsp;
            <span className="text-slate-400">Drag to move &middot; Resize from corners</span>
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => {
              const loadAll = async () => {
                const results: Record<string, Array<Record<string, unknown>>> = {};
                for (const w of widgets) {
                  results[w.id] = await fetchWidgetData(w);
                }
                setWidgetData(results);
              };
              loadAll();
            }}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium hover:bg-slate-50"
          >
            Refresh
          </button>
          <button
            onClick={() => {
              setEditingWidget(null);
              setShowConfigPanel(true);
            }}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white"
          >
            + Add Widget
          </button>
        </div>
      </div>

      {/* Global Filter Bar */}
      <FilterBar filters={globalFilters} columns={allColumns} onChange={handleFiltersChange} />

      {/* Widget Config Panel */}
      {showConfigPanel && (
        <div className="mb-4">
          <WidgetConfigPanel
            projectId={projectId}
            savedQueries={savedQueries}
            datasources={datasources}
            editingWidget={editingWidget}
            onSave={handleSaveWidget}
            onCancel={() => {
              setShowConfigPanel(false);
              setEditingWidget(null);
            }}
          />
        </div>
      )}

      {/* Widget Grid */}
      {widgets.length === 0 && !showConfigPanel ? (
        <div className="rounded-xl border-2 border-dashed border-slate-200 p-12 text-center">
          <p className="text-sm font-semibold text-slate-600">No widgets yet</p>
          <p className="mt-1 text-xs text-slate-400">
            Click &quot;+ Add Widget&quot; to configure your first chart
          </p>
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
            <div key={w.id} className="relative">
              <div className="widget-drag-handle absolute left-0 right-0 top-0 z-10 h-7 cursor-grab" />
              <WidgetRenderer
                widget={w}
                data={widgetData[w.id] ?? []}
                onEdit={() => handleEditWidget(w)}
                onDelete={() => handleDeleteWidget(w.id)}
              />
            </div>
          ))}
        </ResponsiveGridLayout>
      ) : null}
    </div>
  );
}
