"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { Dashboard, WidgetConfig, WidgetType, DashboardConfig } from "./types";
import { WidgetRenderer } from "./WidgetRenderer";

const WIDGET_TYPES: { type: WidgetType; label: string; icon: string }[] = [
  { type: "bar", label: "Bar Chart", icon: "📊" },
  { type: "line", label: "Line Chart", icon: "📈" },
  { type: "pie", label: "Pie / Donut", icon: "🍩" },
  { type: "area", label: "Area Chart", icon: "📉" },
  { type: "kpi", label: "KPI / Number", icon: "🔢" },
  { type: "table", label: "Data Table", icon: "📋" },
];

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

  const [widgetData, setWidgetData] = useState<Record<string, Array<Record<string, unknown>>>>({});
  const [showAddWidget, setShowAddWidget] = useState(false);
  const [editingWidget, setEditingWidget] = useState<WidgetConfig | null>(null);

  // Widget form state
  const [wTitle, setWTitle] = useState("");
  const [wType, setWType] = useState<WidgetType>("bar");
  const [wSourceKind, setWSourceKind] = useState<"query" | "datasource">("query");
  const [wSourceId, setWSourceId] = useState("");
  const [wXKey, setWXKey] = useState("");
  const [wYKey, setWYKey] = useState("");
  const [wColSpan, setWColSpan] = useState(6);

  const updateMutation = useMutation({
    mutationFn: (body: { config: DashboardConfig }) =>
      apiClient.put(`/api/projects/${projectId}/dashboards/${dashboard.id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-dashboards", projectId] });
    },
  });

  const fetchWidgetData = useCallback(async (w: WidgetConfig) => {
    try {
      if (w.dataSource.kind === "query" && w.dataSource.queryId) {
        const query = savedQueries.find((q) => q.id === w.dataSource.queryId);
        if (query?.sql_text) {
          const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
            "/api/query/execute",
            { sql: query.sql_text, project_id: projectId }
          );
          return resp.rows ?? [];
        }
      } else if (w.dataSource.kind === "datasource" && w.dataSource.viewName) {
        const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
          "/api/query/datasource",
          { tableName: w.dataSource.viewName, limit: 100, project_id: projectId }
        );
        return resp.rows ?? [];
      }
    } catch {
      // query may not be runnable yet
    }
    return [];
  }, [savedQueries, projectId]);

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

  const resetWidgetForm = () => {
    setWTitle("");
    setWType("bar");
    setWSourceKind("query");
    setWSourceId("");
    setWXKey("");
    setWYKey("");
    setWColSpan(6);
    setEditingWidget(null);
  };

  const handleAddWidget = () => {
    if (!wTitle.trim()) return;
    const newWidget: WidgetConfig = {
      id: editingWidget?.id ?? `w-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      type: wType,
      title: wTitle,
      dataSource:
        wSourceKind === "query"
          ? { kind: "query", queryId: Number(wSourceId) || 0 }
          : { kind: "datasource", viewName: wSourceId },
      xKey: wXKey || "category",
      yKey: wYKey || "value",
      colSpan: wColSpan,
      position: editingWidget?.position ?? widgets.length,
    };

    let updatedWidgets: WidgetConfig[];
    if (editingWidget) {
      updatedWidgets = widgets.map((w) => (w.id === editingWidget.id ? newWidget : w));
    } else {
      updatedWidgets = [...widgets, newWidget];
    }

    updateMutation.mutate({ config: { widgets: updatedWidgets } });
    resetWidgetForm();
    setShowAddWidget(false);
  };

  const handleDeleteWidget = (id: string) => {
    const updatedWidgets = widgets.filter((w) => w.id !== id);
    updateMutation.mutate({ config: { widgets: updatedWidgets } });
  };

  const handleEditWidget = (w: WidgetConfig) => {
    setEditingWidget(w);
    setWTitle(w.title);
    setWType(w.type);
    setWSourceKind(w.dataSource.kind === "query" ? "query" : "datasource");
    setWSourceId(
      w.dataSource.kind === "query"
        ? String(w.dataSource.queryId ?? "")
        : w.dataSource.viewName ?? ""
    );
    setWXKey(w.xKey);
    setWYKey(w.yKey);
    setWColSpan(w.colSpan);
    setShowAddWidget(true);
  };

  const colSpanClass = (span: number) => {
    if (span >= 12) return "col-span-12";
    if (span >= 6) return "col-span-12 md:col-span-6";
    return "col-span-12 md:col-span-6 lg:col-span-3";
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <button onClick={onBack} className="mb-1 text-xs text-blue-600 hover:underline">
            ← Back to Dashboards
          </button>
          <h2 className="text-lg font-bold text-slate-900">{dashboard.name}</h2>
          {dashboard.description && (
            <p className="text-xs text-slate-500">{dashboard.description}</p>
          )}
          <p className="text-[10px] text-slate-400">
            {widgets.length} widget{widgets.length !== 1 ? "s" : ""} · Status: {dashboard.status}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => {
              resetWidgetForm();
              setShowAddWidget(true);
            }}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
          >
            + Add Widget
          </button>
        </div>
      </div>

      {/* Add/Edit Widget Panel */}
      {showAddWidget && (
        <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
          <h3 className="mb-3 text-sm font-bold text-slate-800">
            {editingWidget ? "Edit Widget" : "Add Widget"}
          </h3>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-600">Title</label>
              <input
                className="w-full rounded border border-slate-200 px-2 py-1.5 text-xs outline-none focus:border-blue-500"
                value={wTitle}
                onChange={(e) => setWTitle(e.target.value)}
                placeholder="Widget title"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-600">Type</label>
              <select
                className="w-full rounded border border-slate-200 px-2 py-1.5 text-xs outline-none"
                value={wType}
                onChange={(e) => setWType(e.target.value as WidgetType)}
              >
                {WIDGET_TYPES.map((wt) => (
                  <option key={wt.type} value={wt.type}>
                    {wt.icon} {wt.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-600">Data Source</label>
              <select
                className="w-full rounded border border-slate-200 px-2 py-1.5 text-xs outline-none"
                value={`${wSourceKind}:${wSourceId}`}
                onChange={(e) => {
                  const [kind, id] = e.target.value.split(":") as ["query" | "datasource", string];
                  setWSourceKind(kind);
                  setWSourceId(id);
                }}
              >
                <option value="query:">Select...</option>
                {savedQueries.map((q) => (
                  <option key={`q-${q.id}`} value={`query:${q.id}`}>
                    Query: {q.name}
                  </option>
                ))}
                {datasources.map((ds) => (
                  <option key={`ds-${ds.viewName}`} value={`datasource:${ds.viewName}`}>
                    {ds.fileName}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-600">X Axis</label>
                <input
                  className="w-full rounded border border-slate-200 px-2 py-1.5 text-xs outline-none"
                  value={wXKey}
                  onChange={(e) => setWXKey(e.target.value)}
                  placeholder="column"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-600">Y Axis</label>
                <input
                  className="w-full rounded border border-slate-200 px-2 py-1.5 text-xs outline-none"
                  value={wYKey}
                  onChange={(e) => setWYKey(e.target.value)}
                  placeholder="column"
                />
              </div>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <div className="flex gap-1">
              {([
                { v: 3, l: "1/4" },
                { v: 6, l: "1/2" },
                { v: 12, l: "Full" },
              ] as const).map((s) => (
                <button
                  key={s.v}
                  onClick={() => setWColSpan(s.v)}
                  className={`rounded px-2 py-1 text-[10px] font-medium ${
                    wColSpan === s.v
                      ? "bg-blue-600 text-white"
                      : "border border-slate-200 text-slate-600"
                  }`}
                >
                  {s.l}
                </button>
              ))}
            </div>
            <div className="ml-auto flex gap-2">
              <button
                onClick={() => {
                  setShowAddWidget(false);
                  resetWidgetForm();
                }}
                className="rounded px-3 py-1.5 text-xs text-slate-500 hover:text-slate-700"
              >
                Cancel
              </button>
              <button
                onClick={handleAddWidget}
                disabled={!wTitle.trim()}
                className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {editingWidget ? "Save Changes" : "Add Widget"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Widget grid */}
      {widgets.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed border-slate-200 py-16 text-center">
          <div className="text-3xl">📊</div>
          <h3 className="mt-2 text-sm font-semibold text-slate-700">No widgets yet</h3>
          <p className="mt-1 text-xs text-slate-500">Click &quot;+ Add Widget&quot; to start building your dashboard.</p>
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
