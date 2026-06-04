"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  const [editingWidget, setEditingWidget] = useState<WidgetConfig | null>(null);

  // Collect all view names to fetch schema for filter bar
  const viewNames = useMemo(() => {
    const names = new Set<string>();
    widgets.forEach((w) => {
      if (w.dataSource.kind === "datasource" && w.dataSource.viewName) {
        names.add(w.dataSource.viewName);
      }
    });
    return Array.from(names);
  }, [widgets]);

  // Fetch schema for first datasource (for filter bar columns)
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

  // Convert global filters to WidgetFilter[] for the API
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

  // Fetch data for all widgets using the widget-query endpoint
  const fetchWidgetData = useCallback(async (w: WidgetConfig) => {
    try {
      // Use the new widget-query endpoint if widget has xColumn/yColumn
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
      // Query-based
      if (w.dataSource.kind === "query" && w.dataSource.queryId) {
        const query = savedQueries.find((q) => q.id === w.dataSource.queryId);
        if (query?.sql_text) {
          const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
            "/api/query/execute",
            { sql: query.sql_text, project_id: projectId }
          );
          return resp.rows ?? [];
        }
      }
    } catch {
      // query may not be runnable yet
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
      updatedWidgets = widgets.map((w) => (w.id === editingWidget.id ? { ...widget, position: w.position } : w));
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

  const colSpanClass = (span: number) => {
    const map: Record<number, string> = {
      3: "col-span-3",
      4: "col-span-4",
      6: "col-span-6",
      8: "col-span-8",
      12: "col-span-12",
    };
    return map[span] || "col-span-6";
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div>
          <button
            onClick={onBack}
            className="mb-1 text-xs font-medium text-blue-600 hover:underline"
          >
            &larr; Back to Dashboards
          </button>
          <h2 className="text-lg font-bold text-slate-900">{dashboard.name}</h2>
          <p className="text-[11px] text-slate-500">
            {widgets.length} widget{widgets.length !== 1 ? "s" : ""} &middot; Status:{" "}
            <span className="font-medium">{dashboard.status}</span>
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => {
              // Re-fetch all data
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
            savedQueries={savedQueries.map((q) => ({ id: q.id, name: q.name }))}
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
      ) : (
        <div className="grid grid-cols-12 gap-4">
          {widgets.map((w) => (
            <div key={w.id} className={colSpanClass(w.colSpan)}>
              <WidgetRenderer
                widget={w}
                data={widgetData[w.id] ?? []}
                onEdit={() => handleEditWidget(w)}
                onDelete={() => handleDeleteWidget(w.id)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
