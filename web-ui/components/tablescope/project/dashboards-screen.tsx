"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconChartBar,
  IconLayoutDashboard,
  IconPlus,
  IconSparkles,
} from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { StatBar } from "@/components/tablescope/project/overview-screen/stat-bar";
import {
  useProjectDashboards,
  useProjectQueries,
  useProjectDataSources,
  widgetCount,
  type Dashboard,
} from "@/lib/ui/use-project-data";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { DashboardDetailView } from "@/components/tablescope/project/detail-views";
import { AIDashboardDesigner } from "@/components/tablescope/project/ai-dashboard-designer";
import { PRESET_LABELS } from "@/components/tablescope/project/itsm-dashboards/ItsmDashboardContent";
import { DashboardOverview } from "@/components/tablescope/project/dashboard-templates/dashboard-overview";
import { DashboardTemplateDialog } from "@/components/tablescope/project/dashboard-templates/template-dialog";
import {
  groupDashboards,
  virtualItsmDashboardConfig,
} from "@/components/tablescope/project/dashboard-templates/groups";
import { useToasts, ToastViewport } from "@/components/ui/toast";
import { createHomePin } from "@/lib/api/home-pins";
import type { WidgetConfig } from "@/components/dashboard/types";
import type { DashboardGroup, DashboardGroupRecord } from "@/components/tablescope/project/dashboard-templates/types";

export function DashboardsScreen({
  projectId,
  dashboardId,
}: {
  projectId: string;
  dashboardId?: string;
}) {
  const { data, isLoading } = useProjectDashboards(projectId);
  const { data: queries } = useProjectQueries(projectId);
  const { data: sources } = useProjectDataSources(projectId);
  const { data: currentUser } = useCurrentUser();
  const queryClient = useQueryClient();
  const realRows = useMemo(() => data ?? [], [data]);
  const itsmPresets = useMemo<Dashboard[]>(() => {
    if (!currentUser?.tenant.servicenowItsmDashboardsV2Enabled) return [];
    const now = new Date().toISOString();
    return Object.entries(PRESET_LABELS).map(([key, label], i) => ({
      id: -(i + 1),
      project_id: Number(projectId),
      tenant_id: 0,
      owner_id: null,
      name: label,
      description: "Live operational metrics, trends and supporting drilldown detail.",
      status: "published",
      config: virtualItsmDashboardConfig(key),
      ai_generated: true,
      view_count: 0,
      created_at: now,
      updated_at: now,
    }));
  }, [currentUser, projectId]);
  const rows = useMemo(() => [...itsmPresets, ...realRows], [itsmPresets, realRows]);
  const { data: persistedGroups } = useQuery<DashboardGroupRecord[]>({ queryKey: ["project", projectId, "dashboard-groups"], queryFn: () => apiClient.get(`/api/projects/${projectId}/dashboard-groups`), enabled: Boolean(projectId) });
  const groups = useMemo(() => groupDashboards(rows, persistedGroups ?? []), [persistedGroups, rows]);
  const [viewingId, setViewingId] = useState<number | null>(
    dashboardId ? Number(dashboardId) : null,
  );
  const viewing = rows.find((d) => d.id === viewingId) ?? null;
  const [designer, setDesigner] = useState<{
    open: boolean;
    dashboardGroupId?: number;
    dashboardGroupName?: string;
  }>({ open: false });
  const [templateOpen, setTemplateOpen] = useState(false);
  const { toasts, push, dismiss } = useToasts();

  // Id of a freshly-created dashboard that has NOT yet been explicitly saved.
  // While set, the dashboard is an ephemeral draft: closing the editor without
  // saving (or navigating away/closing the tab) deletes it. A successful save
  // (`onPersisted`) clears this so the dashboard is kept.
  const draftIdRef = useRef<number | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete(`/api/projects/${projectId}/dashboards/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "dashboards"],
      }),
  });

  // A draft becomes "kept" the moment the user persists any change in the editor.
  const handlePersisted = useCallback(() => {
    draftIdRef.current = null;
  }, []);

  const pinMutation = useMutation({
    mutationFn: createHomePin,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["home-pins"] });
      push("Widget pinned to Home", "success");
    },
    onError: (err: unknown) => {
      push(err instanceof Error ? err.message : "Pin failed", "error");
    },
  });

  const handlePinWidget = useCallback(
    (widget: WidgetConfig, data: unknown[], dashboardId: number) => {
      pinMutation.mutate({
        pin_type: "live_widget",
        pin_key: `widget:${dashboardId}:${widget.id}`,
        title: widget.title || "Pinned widget",
        project_id: Number(projectId),
        config: {
          widget: widget as unknown as Record<string, unknown>,
          cachedData: { columns: data.length > 0 ? Object.keys(data[0] as object) : [], rows: data },
        },
        layout: {
          x: 0,
          y: 0,
          w: widget.gridW ?? widget.colSpan ?? 6,
          h: widget.gridH ?? 4,
        },
      });
    },
    [pinMutation, projectId],
  );

  // Close the editor. If the open dashboard is still an untouched draft, delete it.
  const handleCloseViewer = useCallback(() => {
    const id = viewingId;
    setViewingId(null);
    if (id != null && draftIdRef.current === id) {
      draftIdRef.current = null;
      deleteMutation.mutate(id);
    }
  }, [viewingId, deleteMutation]);

  const handleDeleteDashboard = useCallback(
    (d: Dashboard) => {
      if (d.id < 0) {
        push("ServiceNow preset dashboards cannot be deleted", "info");
        return;
      }
      if (
        typeof window !== "undefined" &&
        !window.confirm(`Delete dashboard "${d.name}"? This cannot be undone.`)
      ) {
        return;
      }
      if (draftIdRef.current === d.id) draftIdRef.current = null;
      deleteMutation.mutate(d.id);
    },
    [deleteMutation, push],
  );

  // Auto-delete a pristine draft on tab close / refresh / navigating away.
  useEffect(() => {
    const flush = () => {
      if (draftIdRef.current != null) {
        apiClient.deleteBeacon(
          `/api/projects/${projectId}/dashboards/${draftIdRef.current}`,
        );
        draftIdRef.current = null;
      }
    };
    window.addEventListener("beforeunload", flush);
    return () => {
      window.removeEventListener("beforeunload", flush);
      flush();
    };
  }, [projectId]);

  const viewingGroup = viewing
    ? groups.find((group) => group.dashboards.some((dashboard) => dashboard.id === viewing.id))
    : undefined;
  const existingTemplateIds = useMemo(
    () => new Set(groups.map((group) => group.templateId).filter((id): id is string => Boolean(id))),
    [groups],
  );
  const statItems = useMemo(
    () => [
      {
        key: "dashboards",
        icon: IconLayoutDashboard,
        iconClass: "bg-brand-50 text-brand-700",
        value: rows.length,
        label: "Total dashboards",
      },
      {
        key: "ai-generated",
        icon: IconSparkles,
        iconClass: "bg-warning-bg text-warning",
        value: rows.filter((dashboard) => dashboard.ai_generated).length,
        label: "AI-generated",
      },
      {
        key: "widgets",
        icon: IconChartBar,
        iconClass: "bg-success-bg text-success",
        value: rows.reduce((total, dashboard) => total + widgetCount(dashboard.config), 0),
        label: "Widgets",
      },
    ],
    [rows],
  );

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-dashboards"
      breadcrumbLabel="Dashboards"
      showProjectHeader={!viewing}
      headerActions={
        !viewing ? (
          <>
            <Button variant="secondary" onClick={() => setDesigner({ open: true })}>
              <IconSparkles size={14} />
              Create with AI
            </Button>
            <Button variant="primary" onClick={() => setTemplateOpen(true)}>
              <IconPlus size={14} />
              Add dashboard template
            </Button>
          </>
        ) : null
      }
    >
      {viewing ? (
        <DashboardDetailView
          projectId={projectId}
          dashboard={viewing}
          savedQueries={queries ?? []}
          datasources={sources ?? []}
          onBack={handleCloseViewer}
          onPersisted={handlePersisted}
          onPinWidget={handlePinWidget}
          dashboardGroupName={viewingGroup?.name}
          dashboardGroup={viewingGroup?.dashboards}
          onSelectDashboard={setViewingId}
        />
      ) : (
        <>
          <StatBar items={statItems} />
          <DashboardOverview
            groups={groups}
            loading={isLoading}
            onOpenDashboard={setViewingId}
            onAddTemplate={() => setTemplateOpen(true)}
            onDeleteDashboard={handleDeleteDashboard}
          />
        </>
      )}
      <AIDashboardDesigner
        open={designer.open}
        projectId={projectId}
        mode="create"
        dashboardGroupId={designer.dashboardGroupId}
        dashboardGroupName={designer.dashboardGroupName}
        onClose={() => setDesigner({ open: false })}
        onApplied={(id) => {
          setDesigner({ open: false });
          void Promise.all([
            queryClient.invalidateQueries({ queryKey: ["project", projectId, "dashboards"] }),
            queryClient.invalidateQueries({ queryKey: ["project", projectId, "dashboard-groups"] }),
          ]);
          setViewingId(id);
        }}
        notify={push}
      />
      <DashboardTemplateDialog
        open={templateOpen}
        projectId={projectId}
        savedQueries={queries ?? []}
        existingTemplateIds={existingTemplateIds}
        onClose={() => setTemplateOpen(false)}
        onCreated={async (ids) => {
          setTemplateOpen(false);
          await queryClient.invalidateQueries({ queryKey: ["project", projectId, "dashboards"] });
          await queryClient.invalidateQueries({ queryKey: ["project", projectId, "dashboard-groups"] });
          if (ids[0]) setViewingId(ids[0]);
        }}
        onOpenExisting={(templateId) => {
          const group = groups.find((item) => item.templateId === templateId);
          setTemplateOpen(false);
          if (group?.dashboards[0]) setViewingId(group.dashboards[0].id);
        }}
        notify={push}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}
