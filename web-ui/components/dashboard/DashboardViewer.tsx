"use client";


import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useMutation, useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import {
  ResponsiveGridLayout,
  useContainerWidth,
  type EventCallback,
  type Layout,
  type LayoutItem,
} from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import {
  GRID_BREAKPOINTS,
  GRID_COLS,
  GRID_CONTAINER_PADDING,
  GRID_DRAG_CONFIG,
  GRID_MARGIN,
  GRID_RESIZE_CONFIG,
  GRID_ROW_HEIGHT,
} from "@/lib/ui/grid-layout";
import { apiClient } from "@/lib/api-client";
import type {
  Dashboard,
  WidgetConfig,
  DashboardConfig,
  DashboardFilter,
  ColumnInfo,
  WidgetFilter,
  DashboardRuntimeState,
  DashboardDateRange,
  ChartClickEvent,
  CrossFilter,
} from "./types";
import type { QueryScope, QueryScopeFilterResponse } from "@/types/query-scope";
import { WidgetRenderer } from "./WidgetRenderer";
import { OperationalWidgetChart } from "./OperationalInsightGrid";
import { WidgetChartOptionsDialog } from "./WidgetChartOptionsDialog";
import { FilterBar } from "./FilterBar";
import { DateRangeControl } from "./DateRangeControl";
import { DrilldownPanel, type DrilldownState } from "./DrilldownPanel";
import { buildRuntimeWidgetFilters } from "@/lib/dashboard/runtimeFilters";
import { SavedQuery } from "./DashboardViewer/saved-query";
import { Props } from "./DashboardViewer/props";
import { resolveDatePreset, type DatePresetId } from "@/lib/dashboard/dateRange";
import type { DashboardTemplateMetadata } from "@/components/tablescope/project/dashboard-templates/types";
import {
  DimensionSwitcher,
  type DimensionSwitcherOption,
} from "@/components/tablescope/project/dashboard-templates/dimension-switcher";
import {
  AIDashboardDesigner,
  type DashboardDesignerMode,
} from "@/components/tablescope/project/ai-dashboard-designer";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { IconChartBar, IconCheck, IconLayoutGrid, IconRefresh, IconSparkles } from "@tabler/icons-react";
import { DashboardTitleEditor } from "@/components/tablescope/project/dashboard-templates/dashboard-title-editor";
import {
  OperationalBriefStrip,
  OperationalDashboardHeader,
  toOperationalStories,
  type OperationalNarrativeItem,
} from "@/components/tablescope/project/operational-dashboard-shell";
import {
  operationalLayout,
  OPERATIONAL_FREE_POSITION_COMPACTOR,
  OPERATIONAL_IMPROVEMENTS_LAYOUT_ID,
} from "@/lib/dashboard/operationalLayout";

const OPERATIONAL_PERIODS: Array<[DatePresetId, string]> = [
  ["last_30_days", "30 days"],
  ["last_60_days", "60 days"],
  ["last_90_days", "90 days"],
  ["last_6_months", "6 months"],
  ["last_1_year", "1 Year"],
  ["last_2_years", "2 Years"],
];

interface OperationalNarrativeWidget {
  id: string;
  type: "operational_brief" | "improvement_opportunities";
  title?: string;
  summary?: string;
  items?: Array<string | OperationalNarrativeItem>;
  layout?: { position?: number; width?: string; gridX?: number; gridY?: number; gridW?: number; gridH?: number };
}

function operationalNarratives(dashboard: Dashboard): OperationalNarrativeWidget[] {
  const value = dashboard.config?.operationalWidgets;
  return Array.isArray(value) ? value as unknown as OperationalNarrativeWidget[] : [];
}

function templateMetadata(dashboard: Dashboard): DashboardTemplateMetadata | undefined {
  const value = dashboard.config?.dashboardTemplate;
  return value && typeof value === "object" ? (value as unknown as DashboardTemplateMetadata) : undefined;
}

function normalizedPeriod(period?: string): DatePresetId | undefined {
  const mapping: Record<string, DatePresetId> = {
    "30_days": "last_30_days",
    "60_days": "last_60_days",
    "90_days": "last_90_days",
    "6_months": "last_6_months",
    "1_year": "last_1_year",
    "2_years": "last_2_years",
  };
  return period ? (mapping[period] ?? period) as DatePresetId : undefined;
}

function bindingPeriod(period: DatePresetId | undefined, fallback = "30_days"): string {
  const mapping: Partial<Record<DatePresetId, string>> = { last_30_days: "30_days", last_60_days: "60_days", last_90_days: "90_days", last_6_months: "6_months", last_1_year: "1_year", last_2_years: "2_years" };
  return (period && mapping[period]) || fallback;
}
interface TemplateHydration { metrics: Record<string, { value: unknown; previousValue: unknown; deltaPercent: number | null }>; batches: Array<{ metricKeys: string[]; lineage: { kind?: string }; rows: Array<Record<string, unknown>> }>; }


export function DashboardViewer({ dashboard, projectId, savedQueries, datasources, onBack, onPersisted, onPinWidget, dashboardOptions, onSelectDashboard }: Props) {
  const queryClient = useQueryClient();
  const { toasts, push, dismiss } = useToasts();
  const widgets = useMemo(() => dashboard.config?.widgets ?? [], [dashboard.config?.widgets]);
  const globalFilters = useMemo(() => dashboard.config?.globalFilters ?? [], [dashboard.config?.globalFilters]);
  const operational = dashboard.config?.presentation === "operational_insight";
  // AI-Designer-created dashboards always carry a decorative "manual"
  // dimension template with zero bound values (nothing for the picker to
  // filter by) — hide it rather than show a dropdown that only ever reads
  // "All {label}". A real template-bound dimension (values present, or
  // driven by a query) still shows the picker as before.
  const template = templateMetadata(dashboard);
  const hasBoundDimension =
    template?.parameters?.valueSource === "query" ||
    (template?.parameters?.manualValues?.length ?? 0) > 0;
  const initialPeriod = normalizedPeriod(template?.parameters.defaultPeriod);
  const initialResolvedPeriod = initialPeriod ? resolveDatePreset(initialPeriod) : null;
  const { width: containerWidth, containerRef, mounted } = useContainerWidth({
    initialWidth: 1280,
  });

  const [widgetData, setWidgetData] = useState<Record<string, Array<Record<string, unknown>>>>({});
  // Read (not reactive-depended-on) by columnNamesForWidget below, so that
  // callback doesn't have to list `widgetData` as a dependency -- doing so
  // created a fetch loop (see the comment there).
  const widgetDataRef = useRef(widgetData);
  useEffect(() => {
    widgetDataRef.current = widgetData;
  }, [widgetData]);
  const [designerMode, setDesignerMode] = useState<DashboardDesignerMode | null>(null);
  const [dashboardStatus, setDashboardStatus] = useState(dashboard.status);
  // Operational dashboards are read-only by default; drag/resize is gated
  // behind an explicit "Edit layout" toggle so a stray drag can't reshuffle
  // a published dashboard.
  const [editingLayout, setEditingLayout] = useState(false);

  // Ephemeral interaction state (not persisted): date range + cross-filters.
  const [runtime, setRuntime] = useState<DashboardRuntimeState>({
    dateRange: initialPeriod && initialResolvedPeriod
      ? { preset: initialPeriod, ...initialResolvedPeriod }
      : null,
    crossFilters: [],
  });
  const [templateOptions, setTemplateOptions] = useState<string[]>(
    template?.parameters.valueSource === "manual" ? template.parameters.manualValues ?? [] : [],
  );
  const [templateField, setTemplateField] = useState(template?.parameters.dimensionLabel ?? "");
  const [templateValue, setTemplateValue] = useState("");
  const dimensionLabel = template?.parameters.dimensionLabel ?? "Dimension";
  const [templateOptionsLoading, setTemplateOptionsLoading] = useState(false);
  const [drilldown, setDrilldown] = useState<DrilldownState>({
    open: false, loading: false, error: null, title: "", targetQueryName: null, columns: [], rows: [],
  });

  const toggleStatusMutation = useMutation({
    mutationFn: async () => {
      const newStatus = dashboardStatus === "published" ? "draft" : "published";
      await apiClient.put(`/api/projects/${projectId}/dashboards/${dashboard.id}`, { status: newStatus });
      return newStatus;
    },
    onSuccess: (newStatus: string) => {
      setDashboardStatus(newStatus);
      onPersisted?.();
      queryClient.invalidateQueries({ queryKey: ["dashboards", projectId] });
      queryClient.invalidateQueries({ queryKey: ["project", String(projectId), "dashboards"] });
    },
  });
  const renameMutation = useMutation({
    mutationFn: (name: string) =>
      apiClient.put(`/api/projects/${projectId}/dashboards/${dashboard.id}`, { name }),
    onSuccess: () => {
      onPersisted?.();
      queryClient.invalidateQueries({ queryKey: ["project", String(projectId), "dashboards"] });
    },
  });
  const [editingWidget, setEditingWidget] = useState<WidgetConfig | null>(null);

  // A dashboard can have more than one AI-discovered, full-coverage
  // primary dimension assigned; the header's switch icon (only, no more
  // inline label-edit pencil -- labels are now set once, during the AI
  // designer's review step) toggles which one is active. Gated on
  // hasBoundDimension since only a query-backed dimension can ever have
  // assignments -- avoids the request on dashboards that never will.
  const { data: primaryDimensionAssignments = [] } = useQuery({
    queryKey: ["dashboard-primary-dimensions", projectId, dashboard.id],
    queryFn: () =>
      apiClient.get<Array<{ id: number; label: string; is_active: boolean }>>(
        `/api/projects/${projectId}/dashboards/${dashboard.id}/primary-dimensions`,
      ),
    enabled: hasBoundDimension,
  });
  const dimensionSwitcherOptions: DimensionSwitcherOption[] = useMemo(
    () => primaryDimensionAssignments.map((a) => ({ id: a.id, label: a.label, isActive: a.is_active })),
    [primaryDimensionAssignments],
  );
  const activateDimensionMutation = useMutation({
    mutationFn: (assignmentId: number) =>
      apiClient.post(`/api/projects/${projectId}/dashboards/${dashboard.id}/primary-dimensions/${assignmentId}/activate`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard-primary-dimensions", projectId, dashboard.id] });
      onPersisted?.();
    },
  });

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
  const { data: fetchedQueriesRaw } = useQuery({
    queryKey: ["missing-queries", projectId, missingQueryIds],
    queryFn: () =>
      apiClient.get<SavedQuery[]>(`/api/projects/${projectId}/queries`),
    enabled: missingQueryIds.length > 0,
  });
  // A `= []` destructuring default re-allocates a new array every render
  // while `data` stays undefined (query disabled/pending) -- that instability
  // was the third contributor to the render loop fixed above, cascading
  // through allQueries -> fetchWidgetData -> the widget-data fetch effect.
  const fetchedQueries = useMemo(() => fetchedQueriesRaw ?? [], [fetchedQueriesRaw]);

  // Merged list of all queries available to widgets
  const allQueries = useMemo(() => {
    const map = new Map<number, SavedQuery>();
    savedQueries.forEach((q) => map.set(q.id, q));
    fetchedQueries.forEach((q: SavedQuery) => map.set(q.id, q));
    return Array.from(map.values());
  }, [savedQueries, fetchedQueries]);

  useEffect(() => {
    const parameters = template?.parameters;
    if (!parameters || parameters.valueSource !== "query" || !parameters.queryId) return;
    const query = allQueries.find((item) => item.id === parameters.queryId);
    if (!query?.sql_text) return;
    let active = true;
    setTemplateOptionsLoading(true);
    const tableMatch = query.sql_text.match(/FROM\s+"?([A-Za-z0-9_]+)"?/i);
    apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
      "/api/query/datasource",
      {
        tableName: tableMatch ? tableMatch[1] : "dual",
        sql: query.sql_text,
        limit: 500,
        project_id: projectId,
      },
    ).then((response) => {
      if (!active) return;
      const field = response.columns?.[0] ?? parameters.dimensionLabel;
      const values = [...new Set((response.rows ?? []).map((row) => row[field]).filter((value) => value != null).map(String))];
      setTemplateField(field);
      setTemplateOptions(values);
    }).catch(() => {
      if (active) setTemplateOptions([]);
    }).finally(() => {
      if (active) setTemplateOptionsLoading(false);
    });
    return () => { active = false; };
  }, [allQueries, projectId, template]);

  const changeTemplateValue = useCallback((value: string) => {
    setTemplateValue(value);
    setRuntime((previous) => ({
      ...previous,
      crossFilters: [
        ...previous.crossFilters.filter((filter) => filter.id !== "template-dimension"),
        ...(value ? [{
          id: "template-dimension",
          sourceWidgetId: "dashboard-template",
          sourceField: templateField,
          value,
          label: `${dimensionLabel || templateField}: ${value}`,
        }] : []),
      ],
    }));
  }, [dimensionLabel, templateField]);

  const viewNames = useMemo(() => {
    const names = new Set<string>();
    widgets.forEach((w) => {
      if (w.dataSource?.kind === "datasource" && w.dataSource.viewName) {
        names.add(w.dataSource.viewName);
      }
    });
    return Array.from(names);
  }, [widgets]);

  // Fetch the schema for every distinct view so we can (a) populate the filter
  // bar with columns across all widgets and (b) decide which widgets a runtime
  // cross-filter / date range is compatible with.
  const schemaQueries = useQueries({
    queries: viewNames.map((vn) => ({
      queryKey: ["datasource-schema", projectId, vn],
      queryFn: async () =>
        apiClient.get<{ columns: ColumnInfo[] }>(`/api/projects/${projectId}/dashboards/schema/${vn}`),
      enabled: !!vn,
      staleTime: 60_000,
    })),
  });

  // `useQueries` returns a new array reference every render regardless of
  // whether any query's data actually changed, so memoizing directly on
  // `schemaQueries` re-derives `viewColumns` (and everything downstream --
  // columnNamesForWidget, fetchWidgetData, the widget-data fetch effect)
  // every render, which re-triggers that effect every render: the same
  // render-loop class as the widgetData issue fixed above, via a second,
  // independent path. `dataUpdatedAt` is a stable primitive per query that
  // only changes when that query's data actually updates.
  const schemaDataUpdatedAt = schemaQueries.map((q) => q.dataUpdatedAt).join(",");
  const viewColumns = useMemo(() => {
    const map: Record<string, ColumnInfo[]> = {};
    viewNames.forEach((vn, i) => {
      map[vn] = schemaQueries[i]?.data?.columns ?? [];
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewNames, schemaDataUpdatedAt]);

  const allColumns: ColumnInfo[] = useMemo(() => {
    const map = new Map<string, ColumnInfo>();
    for (const cols of Object.values(viewColumns)) {
      for (const c of cols) if (!map.has(c.name)) map.set(c.name, c);
    }
    return Array.from(map.values());
  }, [viewColumns]);

  // Known column names for a widget (used for runtime filter compatibility).
  // Deliberately reads widgetData via the ref above, not as a hook
  // dependency: this callback feeds into fetchWidgetData below, whose own
  // effect is what writes widgetData. Depending on the state it writes
  // created a render loop -- fetch -> setWidgetData -> this callback's
  // identity changes -> fetchWidgetData's identity changes -> its effect
  // re-fires -> fetch again, forever. The ref breaks that cycle while still
  // reading the latest loaded rows when needed.
  const columnNamesForWidget = useCallback((w: WidgetConfig): string[] => {
    if (w.dataSource?.kind === "datasource" && w.dataSource.viewName) {
      const cols = viewColumns[w.dataSource.viewName];
      if (cols && cols.length > 0) return cols.map((c) => c.name);
    }
    const loaded = widgetDataRef.current[w.id];
    if (loaded && loaded.length > 0) return Object.keys(loaded[0]);
    return [];
  }, [viewColumns]);

  const updateMutation = useMutation({
    mutationFn: (body: { config: DashboardConfig }) =>
      apiClient.put(`/api/projects/${projectId}/dashboards/${dashboard.id}`, body),
    onSuccess: () => {
      onPersisted?.();
      queryClient.invalidateQueries({ queryKey: ["project-dashboards", projectId] });
      queryClient.invalidateQueries({ queryKey: ["project", String(projectId), "dashboards"] });
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
        // Persisted global filters + ephemeral runtime filters (cross-filter +
        // date range), applied only to compatible widgets.
        const runtimeFilters = buildRuntimeWidgetFilters(w, runtime, columnNamesForWidget(w));
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
            global_filters: [...globalFiltersForApi(), ...runtimeFilters],
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
          // Query-backed widgets have no other hook for the date-range/
          // cross-filter runtime controls -- their saved SQL is otherwise
          // replayed verbatim regardless of the period selected.
          const runtimeFilters = buildRuntimeWidgetFilters(w, runtime, columnNamesForWidget(w));
          const resp = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(
            "/api/query/datasource",
            {
              tableName, sql: query.sql_text, limit: 500, project_id: projectId,
              global_filters: [...globalFiltersForApi(), ...runtimeFilters],
            }
          );
          return resp.rows ?? [];
        }
      }
    } catch {
      /* widget shows "No data" */
    }
    return [];
  }, [allQueries, projectId, globalFiltersForApi, runtime, columnNamesForWidget]);

  const refreshAllWidgets = useCallback(async () => {
    const results: Record<string, Array<Record<string, unknown>>> = {};
    for (const w of widgets) results[w.id] = await fetchWidgetData(w);
    setWidgetData(results);
  }, [widgets, fetchWidgetData]);

  useEffect(() => {
    const loadAll = async () => {
      const entries = await Promise.all(
        widgets.filter((w) => !w.templateMetricKey || !template?.bindingId).map(async (w) => {
          const rows = await fetchWidgetData(w);
          return [w.id, rows] as const;
        }),
      );
      const results: Record<string, Array<Record<string, unknown>>> = {};
      for (const [id, rows] of entries) results[id] = rows;
      setWidgetData((previous) => ({ ...previous, ...results }));
    };
    if (widgets.length > 0) loadAll();
  }, [widgets, fetchWidgetData, template?.bindingId]);

  useEffect(() => {
    if (!template?.bindingId) return;
    let active = true;
    const period = bindingPeriod(runtime.dateRange?.preset as DatePresetId | undefined, template.parameters.defaultPeriod);
    const selected = templateValue ? `&dimension=${encodeURIComponent(templateValue)}` : "";
    apiClient.get<TemplateHydration>(`/api/projects/${projectId}/dashboard-template-bindings/${template.bindingId}/hydrate?period=${period}${selected}`).then((hydration) => {
      if (!active) return;
      setWidgetData((previous) => {
        const next = { ...previous };
        widgets.forEach((widget) => {
          const key = widget.templateMetricKey; if (!key) return;
          const metric = hydration.metrics[key];
          if (widget.type === "kpi") next[widget.id] = [{ [widget.yColumn || "value"]: metric?.value ?? null, previousValue: metric?.previousValue ?? null, deltaPercent: metric?.deltaPercent ?? null }];
          else { const batch = hydration.batches.find((item) => item.lineage.kind === "dimension" && item.metricKeys.includes(key)); if (batch) next[widget.id] = batch.rows.map((row) => ({ [widget.xColumn || "dimension"]: row.dimension, [widget.yColumn || key]: row[key] })); }
        });
        return next;
      });
    }).catch(() => undefined);
    return () => { active = false; };
  }, [projectId, runtime.dateRange?.preset, template, templateValue, widgets]);

  const handleEditWidget = (w: WidgetConfig) => {
    setEditingWidget(w);
    setDesignerMode("edit_insight");
  };

  const [chartOptionsWidget, setChartOptionsWidget] = useState<WidgetConfig | null>(null);

  const handleApplyChartOptions = useCallback(
    (chartType: string, chartSubtype: string | undefined) => {
      if (!chartOptionsWidget) return;
      const updatedWidgets = widgets.map((w) =>
        w.id === chartOptionsWidget.id
          ? {
              ...w,
              type: chartType as WidgetConfig["type"],
              chartSubtype: chartSubtype as WidgetConfig["chartSubtype"],
            }
          : w,
      );
      updateMutation.mutate({ config: { ...dashboard.config, widgets: updatedWidgets, globalFilters } });
    },
    [chartOptionsWidget, dashboard.config, globalFilters, updateMutation, widgets],
  );

  const [widgetPendingDelete, setWidgetPendingDelete] = useState<WidgetConfig | null>(null);

  const confirmDeleteWidget = useCallback(() => {
    if (!widgetPendingDelete) return;
    const updatedWidgets = widgets.filter((w) => w.id !== widgetPendingDelete.id);
    updateMutation.mutate({ config: { ...dashboard.config, widgets: updatedWidgets, globalFilters } });
    setWidgetPendingDelete(null);
  }, [dashboard.config, globalFilters, updateMutation, widgetPendingDelete, widgets]);

  const handleFiltersChange = (newFilters: DashboardFilter[]) => {
    updateMutation.mutate({ config: { ...dashboard.config, widgets, globalFilters: newFilters } });
  };

  // ── Runtime interactions: cross-filter + drilldown ────────────────

  const setDateRange = useCallback((range: DashboardDateRange | null) => {
    setRuntime((prev) => ({ ...prev, dateRange: range }));
  }, []);

  const addCrossFilter = useCallback((cf: CrossFilter) => {
    setRuntime((prev) => {
      const existing = prev.crossFilters.find(
        (f) => f.sourceField === cf.sourceField && f.sourceWidgetId === cf.sourceWidgetId,
      );
      // Clicking the same value again clears the filter (toggle off).
      if (existing && String(existing.value) === String(cf.value)) {
        return { ...prev, crossFilters: prev.crossFilters.filter((f) => f.id !== existing.id) };
      }
      const without = prev.crossFilters.filter(
        (f) => !(f.sourceField === cf.sourceField && f.sourceWidgetId === cf.sourceWidgetId),
      );
      return { ...prev, crossFilters: [...without, cf] };
    });
  }, []);

  const removeCrossFilter = useCallback((id: string) => {
    setRuntime((prev) => ({ ...prev, crossFilters: prev.crossFilters.filter((f) => f.id !== id) }));
  }, []);

  const clearRuntimeFilters = useCallback(() => {
    setRuntime({ dateRange: null, crossFilters: [] });
  }, []);

  const openDrilldown = useCallback(async (w: WidgetConfig, ev: ChartClickEvent) => {
    setDrilldown({
      open: true, loading: true, error: null,
      title: `Drilldown: ${ev.label}`, targetQueryName: null, columns: [], rows: [],
    });
    try {
      // Resolve the scope: prefer an explicit scopeId, else look one up by the
      // widget's source query + clicked field.
      let scopeId = w.interactions?.scopeId ?? null;
      if (scopeId == null && w.dataSource?.kind === "query" && w.dataSource.queryId) {
        const scopes = await apiClient.get<QueryScope[]>(
          `/api/query-scopes?query_id=${w.dataSource.queryId}`,
        );
        const match = scopes.find(
          (s) => s.source_field.toLowerCase() === ev.sourceField.toLowerCase(),
        );
        scopeId = match?.id ?? null;
      }
      if (scopeId == null) {
        setDrilldown((d) => ({
          ...d, loading: false,
          error: "No drill-down scope is configured for this widget's field. Add a query scope mapping the source field to a target query.",
        }));
        return;
      }
      const res = await apiClient.post<QueryScopeFilterResponse>(
        "/api/query-scopes/filter",
        { scope_id: scopeId, value: ev.value, limit: 1000 },
      );
      setDrilldown({
        open: true, loading: false, error: null,
        title: `Drilldown: ${ev.label}`,
        targetQueryName: res.target_query_name,
        columns: res.columns, rows: res.rows,
      });
    } catch (e) {
      setDrilldown((d) => ({ ...d, loading: false, error: (e as Error).message }));
    }
  }, []);

  const handleElementClick = useCallback((w: WidgetConfig, ev: ChartClickEvent) => {
    const inter = w.interactions;
    const action = inter?.clickAction ?? "none";
    if (!inter?.enabled || action === "none") return;
    if (action === "cross_filter" || action === "drilldown_and_filter") {
      addCrossFilter({
        id: `cf-${w.id}-${ev.sourceField}`,
        sourceWidgetId: w.id,
        sourceField: ev.sourceField,
        value: ev.value,
        label: ev.label,
      });
    }
    if (action === "drilldown" || action === "drilldown_and_filter") {
      openDrilldown(w, ev);
    }
  }, [addCrossFilter, openDrilldown]);

  const narratives = useMemo(() => operationalNarratives(dashboard), [dashboard]);
  const brief = narratives.find((item) => item.type === "operational_brief");
  const improvements = narratives.find((item) => item.type === "improvement_opportunities");
  const headerDashboards = dashboardOptions?.length ? dashboardOptions : [{ id: dashboard.id, name: dashboard.name }];
  // Operational dashboards keep their ITSM presentation while using one
  // React Grid Layout in both view and edit modes. Editing only unlocks the
  // drag and resize controls; the rendered cards and charts do not switch.
  const gridLayoutEditable = operational;

  // ── react-grid-layout ────────────────────────────────────────────
  const colSpanToGridW = (span: number) => Math.min(12, Math.max(2, span));

  const layoutRef = useRef<LayoutItem[]>([]);
  const layouts = useMemo(() => {
    const lg: LayoutItem[] = operational
      ? operationalLayout(widgets, improvements?.layout, (dashboard.config?.operationalLayoutVersion ?? 0) >= 2).filter((item) => improvements || item.i !== OPERATIONAL_IMPROVEMENTS_LAYOUT_ID)
      : widgets.map((w, idx) => ({
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
  }, [dashboard.config?.operationalLayoutVersion, improvements?.layout, operational, widgets]);

  const persistLayout = useCallback((layout: Layout) => {
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
    const improvementLayout = layout.find((item) => item.i === OPERATIONAL_IMPROVEMENTS_LAYOUT_ID);
    const updatedNarratives = narratives.map((item) => item.type === "improvement_opportunities" && improvementLayout
      ? { ...item, layout: { ...item.layout, gridX: improvementLayout.x, gridY: improvementLayout.y, gridW: Math.min(improvementLayout.w, 6), gridH: improvementLayout.h } }
      : item);
    updateMutation.mutate({ config: { ...dashboard.config, widgets: updatedWidgets, globalFilters, ...(operational ? { operationalLayoutVersion: 2, operationalWidgets: updatedNarratives as unknown as Array<Record<string, unknown>> } : {}) } });
  }, [dashboard.config, widgets, globalFilters, narratives, operational, updateMutation]);

  const handleDragStop: EventCallback = useCallback(
    (layout) => persistLayout(layout as unknown as Layout),
    [persistLayout],
  );

  const handleResizeStop: EventCallback = useCallback(
    (layout) => persistLayout(layout as unknown as Layout),
    [persistLayout],
  );

  // Cross-filter chips + "Clear all", shared by both header styles below.
  const runtimeFilterChips = (runtime.crossFilters.length > 0 || runtime.dateRange) && (
    <div className="flex flex-wrap items-center gap-2">
      {runtime.crossFilters.map((cf) => (
        <div key={cf.id} className="flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700">
          <span>{cf.label}</span>
          <button onClick={() => removeCrossFilter(cf.id)} className="text-blue-400 hover:text-blue-700" title="Remove filter">
            <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>
      ))}
      <button onClick={clearRuntimeFilters} className="text-[11px] font-medium text-ink-tertiary hover:text-red-500">
        Clear all
      </button>
    </div>
  );

  return (
    <div className={operational ? "bg-bg-secondary text-ink-primary" : "min-h-screen bg-gray-50"}>
      {operational ? (
        // ── ITSM-style header ───────────────────────────────────────
        // AI-generated dashboards are live the moment they're created (no
        // draft/publish gate), so this header only ever shows "Live" — it
        // mirrors ItsmInsightsDashboardContent.tsx's title+badge+subtitle
        // left side and compact-dropdown right side, wired to this
        // dashboard's own generic filters/period/AI-designer actions
        // instead of the ITSM presets' fixed Site/Region data.
        <div className="px-2 py-2">
          <OperationalDashboardHeader
            title={<DashboardTitleEditor name={dashboard.name} onSave={(name) => renameMutation.mutate(name)} />}
            subtitle={`${dashboard.description ? `${dashboard.description} · ` : ""}${widgets.length} insight${widgets.length !== 1 ? "s" : ""}`}
            live={dashboardStatus === "published"}
            onBack={onBack}
            controls={
              <>
                <label className="sr-only" htmlFor={`operational-period-${dashboard.id}`}>Period</label>
                <select
                  id={`operational-period-${dashboard.id}`}
                  value={runtime.dateRange?.preset ?? initialPeriod ?? "last_1_year"}
                  onChange={(event) => {
                    const preset = event.target.value as DatePresetId;
                    const resolved = resolveDatePreset(preset);
                    if (resolved) setDateRange({ preset, ...resolved });
                  }}
                  className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none"
                >
                  {OPERATIONAL_PERIODS.map(([value, label]) => <option key={value} value={value}>Period: {label}</option>)}
                </select>
                {template?.parameters && hasBoundDimension && (
                  <>
                    {/* Dimension type and dimension value are separate
                        controls, matching the ITSM header. */}
                    <span className="flex h-8 items-center gap-1 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs font-medium text-ink-primary">
                      <span>{dimensionLabel}</span>
                      <DimensionSwitcher
                        options={dimensionSwitcherOptions}
                        onSelect={(id) => activateDimensionMutation.mutate(id)}
                        pending={activateDimensionMutation.isPending}
                      />
                    </span>
                    <select
                      value={templateValue}
                      onChange={(event) => changeTemplateValue(event.target.value)}
                      disabled={templateOptionsLoading}
                      aria-label={`${dimensionLabel} filter`}
                      className="h-8 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none"
                    >
                      <option value="">All {dimensionLabel}</option>
                      {templateOptions.map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </>
                )}
                {headerDashboards.length > 1 && (
                  <select
                    value={dashboard.id}
                    onChange={(event) => onSelectDashboard?.(Number(event.target.value))}
                    aria-label="Dashboard"
                    disabled={!onSelectDashboard}
                    className="h-8 max-w-56 rounded-md border border-line-secondary bg-bg-primary px-2 text-xs text-ink-primary focus:border-brand-500 focus:outline-none disabled:opacity-100"
                  >
                    {headerDashboards.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                )}
                {gridLayoutEditable && (
                  <Button
                    variant={editingLayout ? "brandSoft" : "secondary"}
                    size="md"
                    title={editingLayout ? "Done editing layout" : "Edit Layout"}
                    aria-label={editingLayout ? "Done editing layout" : "Edit Layout"}
                    aria-pressed={editingLayout}
                    onClick={() => setEditingLayout((value) => !value)}
                  >
                    {editingLayout ? <IconCheck size={14} /> : <IconLayoutGrid size={14} />}
                    {editingLayout ? "Done" : "Edit Layout"}
                  </Button>
                )}
                <Button
                  variant="secondary"
                  size="icon"
                  title="Edit Dashboard"
                  aria-label="Edit Dashboard"
                  onClick={() => { setEditingWidget(null); setDesignerMode("edit_dashboard"); }}
                >
                  <IconSparkles size={14} />
                </Button>
                <Button
                  variant="secondary"
                  size="icon"
                  title="Refresh dashboard"
                  aria-label="Refresh dashboard"
                  onClick={() => void refreshAllWidgets()}
                >
                  <IconRefresh size={14} />
                </Button>
                <button
                  onClick={() => { setEditingWidget(null); setDesignerMode("add_insight"); }}
                  className="flex h-8 items-center gap-1 rounded-md bg-brand-600 px-2.5 text-xs font-bold text-white transition-colors hover:bg-brand-700"
                >
                  <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" /></svg>
                  Add insight
                </button>
              </>
            }
          />

          {runtimeFilterChips && <div className="mt-2">{runtimeFilterChips}</div>}
          {allColumns.length > 0 && (
            <div className="mt-2 border-t border-line-tertiary pt-2">
              <FilterBar filters={globalFilters} columns={allColumns} onChange={handleFiltersChange} />
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="rounded-t-xl bg-slate-800 px-5 py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <button onClick={onBack} className="flex items-center gap-1 text-[11px] font-medium text-slate-400 transition-colors hover:text-white">
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
                  onClick={refreshAllWidgets}
                  className="flex items-center gap-1 rounded-md border border-slate-600 px-2.5 py-1 text-[10px] font-medium text-slate-300 transition-colors hover:bg-slate-700"
                >
                  <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                  Refresh
                </button>
              </div>
            </div>
          </div>

          {/* ── Filter Bar ───────────────────────────────────────────── */}
          <div className="border-b border-slate-200 bg-white px-5 py-2">
            <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2">
              {template?.parameters && hasBoundDimension && (
                <label className="flex items-center gap-1.5 text-[11px] font-medium text-ink-secondary">
                  <span>{dimensionLabel}</span>
                  <DimensionSwitcher
                    options={dimensionSwitcherOptions}
                    onSelect={(id) => activateDimensionMutation.mutate(id)}
                    pending={activateDimensionMutation.isPending}
                  />
                  <select
                    value={templateValue}
                    onChange={(event) => changeTemplateValue(event.target.value)}
                    disabled={templateOptionsLoading}
                    className="rounded-md border border-line-secondary bg-bg-primary px-2 py-1 text-[11px] text-ink-primary"
                  >
                    <option value="">All {dimensionLabel}</option>
                    {templateOptions.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>
              )}
              <DateRangeControl value={runtime.dateRange} onChange={setDateRange} />
              {runtime.crossFilters.length > 0 && <div className="h-4 w-px bg-slate-200" />}
              {runtime.crossFilters.map((cf) => (
                <div key={cf.id} className="flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-700">
                  <span>{cf.label}</span>
                  <button onClick={() => removeCrossFilter(cf.id)} className="text-blue-400 hover:text-blue-700" title="Remove filter">
                    <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" /></svg>
                  </button>
                </div>
              ))}
              {(runtime.crossFilters.length > 0 || runtime.dateRange) && (
                <button onClick={clearRuntimeFilters} className="text-[11px] font-medium text-slate-400 hover:text-red-500">
                  Clear all
                </button>
              )}
            </div>
            <FilterBar filters={globalFilters} columns={allColumns} onChange={handleFiltersChange} />
          </div>
        </>
      )}

      {/* ── Widget Grid ──────────────────────────────────────────── */}
      <div className={operational ? "py-3" : "px-4 py-4"}>
        {operational && brief && (
          <OperationalBriefStrip
            stories={toOperationalStories(brief.items, brief.summary)}
            subtitle={brief.summary || "The story behind the selected period"}
          />
        )}
        {operational && editingLayout && (
          <div className="mb-3 mt-3 rounded-md border border-dashed border-brand-200 bg-brand-50/40 px-3 py-2 text-xs text-ink-secondary">
            Drag a widget by its header and resize it from any visible edge or corner handle. On a touchscreen, press and drag directly; empty grid space is preserved and other widgets will not move.
          </div>
        )}
        {widgets.length === 0 ? (
          <div className={operational ? "flex flex-col items-center justify-center rounded-xl border border-dashed border-line-secondary bg-bg-primary py-20" : "flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-white py-20"}>
            <svg className="mb-3 h-12 w-12 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
            <p className="text-sm font-semibold text-slate-600">{operational ? "Describe the operational decisions you want to support" : "No widgets yet"}</p>
            <p className="mt-1 text-xs text-slate-400">{operational ? "AI will select, validate and wire the appropriate KPI cards and charts." : "Click + Add Widget to start building your dashboard"}</p>
            {operational && <button type="button" onClick={() => setDesignerMode("edit_dashboard")} className="mt-3 rounded-md bg-brand-600 px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-brand-700">Design with AI</button>}
          </div>
        ) : widgets.length > 0 ? (
          <div
            ref={containerRef}
            className={`w-full ${
              operational && editingLayout
                ? "[&_.widget-drag-handle]:touch-none [&_.widget-drag-handle]:select-none [&_.react-resizable-handle]:!z-20 [&_.react-resizable-handle]:!h-11 [&_.react-resizable-handle]:!w-11 [&_.react-resizable-handle]:!opacity-100 [&_.react-resizable-handle]:touch-none [&_.react-resizable-handle]:select-none"
                : ""
            }`}
          >
            {mounted && (
              <ResponsiveGridLayout
                className="layout"
                layouts={layouts}
                breakpoints={GRID_BREAKPOINTS}
                cols={GRID_COLS}
                rowHeight={GRID_ROW_HEIGHT}
                margin={GRID_MARGIN}
                containerPadding={GRID_CONTAINER_PADDING}
                compactor={operational ? OPERATIONAL_FREE_POSITION_COMPACTOR : undefined}
                onDragStop={handleDragStop}
                onResizeStop={handleResizeStop}
                dragConfig={{
                  ...GRID_DRAG_CONFIG,
                  enabled: !operational || editingLayout,
                  // RGL's drag threshold reads MouseEvent coordinates. Use
                  // immediate activation for touch input so iPad gestures are
                  // never lost while Safari decides whether to scroll.
                  threshold: operational ? 0 : GRID_DRAG_CONFIG.threshold,
                }}
                resizeConfig={{ ...GRID_RESIZE_CONFIG, enabled: !operational || editingLayout }}
                width={containerWidth}
              >
            {widgets.map((w) => (
              <div key={w.id}>
                <div className={`h-full overflow-hidden border bg-white transition-shadow ${operational ? "rounded-xl border-line-tertiary shadow-none hover:border-brand-200" : "rounded-lg border-slate-200 shadow-sm hover:shadow-md"}`}>
                  {/* Widget header — drag handle + metadata badges */}
                  <div className={`widget-drag-handle flex items-center justify-between bg-white px-3 ${!operational || editingLayout ? "cursor-grab active:cursor-grabbing" : "cursor-default"} ${operational ? "pb-1 pt-3" : "border-b border-slate-100 py-2"}`}>
                    <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        {!operational && <svg className="h-3 w-3 flex-shrink-0 text-slate-300" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="5" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="12" cy="19" r="2"/></svg>}
                        <h4 className={operational ? "truncate text-sm font-semibold text-ink-primary" : "truncate text-xs font-bold text-slate-800"}>{w.title || "Untitled"}</h4>
                      </div>
                      {!operational && w.aggregation && w.yColumn && (
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
                    <div className={`ml-2 flex flex-shrink-0 gap-0.5 ${operational ? "opacity-60 transition-opacity hover:opacity-100" : ""}`}>
                      {onPinWidget && (
                        <button
                          onClick={() => onPinWidget(w, widgetData[w.id] ?? [], dashboard.id)}
                          title="Pin to Home"
                          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
                        >
                          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" /></svg>
                        </button>
                      )}
                      {operational && w.type !== "kpi" && (
                        <button
                          type="button"
                          onClick={() => setChartOptionsWidget(w)}
                          title="Chart options"
                          className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                        >
                          <IconChartBar size={14} />
                        </button>
                      )}
                      <button onClick={() => handleEditWidget(w)} title={operational ? "Modify with AI" : "Edit"} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors">
                        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                      </button>
                      <button onClick={() => setWidgetPendingDelete(w)} title="Delete widget" className="rounded p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600">
                        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                      </button>
                    </div>
                  </div>
                  {/* Chart */}
                  <div className={operational ? "overflow-hidden px-3 pb-3 pt-1" : "overflow-hidden p-3"} style={{ height: operational ? "calc(100% - 38px)" : "calc(100% - 52px)" }}>
                    {operational && w.type !== "kpi" ? (
                      // Render through the same ITSM-styled chart the
                      // operational dashboard uses, not
                      // the generic WidgetRenderer -- entering Edit Layout
                      // must only add drag/resize, not change how the chart
                      // itself looks.
                      <OperationalWidgetChart
                        widget={w}
                        rows={widgetData[w.id] ?? []}
                        className="h-full"
                        onElementClick={handleElementClick}
                      />
                    ) : (
                      <WidgetRenderer
                        widget={w}
                        data={widgetData[w.id] ?? []}
                        operational={operational}
                        onElementClick={(ev) => handleElementClick(w, ev)}
                      />
                    )}
                  </div>
                </div>
              </div>
            ))}
            {operational && improvements && (
              <div key={OPERATIONAL_IMPROVEMENTS_LAYOUT_ID}>
                <div className="h-full overflow-hidden rounded-xl border border-line-tertiary bg-white p-4">
                  <div className={`widget-drag-handle flex items-start justify-between gap-3 ${editingLayout ? "cursor-grab active:cursor-grabbing" : "cursor-default"}`}>
                    <div>
                      <h4 className="text-sm font-semibold text-ink-primary">{improvements.title || "Best Improvement Opportunities"}</h4>
                      <p className="mt-0.5 text-[11px] text-ink-tertiary">Prioritized by operational impact</p>
                    </div>
                    <button type="button" onClick={() => { setEditingWidget(null); setDesignerMode("edit_dashboard"); }} title="Edit with AI" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
                      <IconSparkles size={14} />
                    </button>
                  </div>
                  <ol className="mt-3 space-y-2.5">
                    {(improvements.items ?? []).slice(0, 5).map((item, index) => (
                      <li key={`improvement-${index}`} className="flex gap-2 border-b border-line-tertiary pb-2 text-[11px] leading-4 text-ink-secondary last:border-0">
                        <span className="font-semibold text-brand-600">{index + 1}.</span>
                        <span>{typeof item === "string" ? item : item.detail || item.label}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            )}
              </ResponsiveGridLayout>
            )}
          </div>
        ) : null}
      </div>

      <DrilldownPanel state={drilldown} onClose={() => setDrilldown((d) => ({ ...d, open: false }))} />
      <AIDashboardDesigner
        open={designerMode !== null}
        projectId={String(projectId)}
        mode={designerMode ?? "add_insight"}
        dashboardId={dashboard.id}
        targetInsightId={designerMode === "edit_insight" ? editingWidget?.id : undefined}
        existingWidgets={designerMode === "edit_dashboard" ? widgets : undefined}
        dashboardGroupId={template?.dashboardGroupId}
        dashboardGroupName={template?.groupName}
        initialPrompt={designerMode === "edit_insight" && editingWidget ? `Change “${editingWidget.title}” to show ` : ""}
        onClose={() => { setDesignerMode(null); setEditingWidget(null); }}
        onApplied={() => {
          setDesignerMode(null);
          setEditingWidget(null);
          onPersisted?.();
          void queryClient.invalidateQueries({ queryKey: ["project", String(projectId), "dashboards"] });
        }}
        notify={push}
      />
      {chartOptionsWidget && (
        <WidgetChartOptionsDialog
          widget={chartOptionsWidget}
          rows={widgetData[chartOptionsWidget.id] ?? []}
          projectId={projectId}
          open={chartOptionsWidget !== null}
          onClose={() => setChartOptionsWidget(null)}
          onApply={handleApplyChartOptions}
        />
      )}
      <ConfirmDialog
        open={widgetPendingDelete !== null}
        title="Delete this widget?"
        message={`Remove "${widgetPendingDelete?.title || "this widget"}" from the dashboard? This cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={confirmDeleteWidget}
        onCancel={() => setWidgetPendingDelete(null)}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
