"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { IconSparkles, IconPlus, IconLayoutDashboard, IconTrash } from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/ui/format";
import { accentFor } from "@/lib/ui/color";
import {
  useProjectDashboards,
  useProjectQueries,
  useProjectDataSources,
  widgetCount,
  type Dashboard,
} from "@/lib/ui/use-project-data";
import { DashboardDetailView } from "@/components/tablescope/project/detail-views";
import { AIDashboardSuggestionsModal } from "@/components/tablescope/project/ai-dashboard-suggestions-modal";
import { useToasts, ToastViewport } from "@/components/ui/toast";
import { createHomePin } from "@/lib/api/home-pins";
import type { WidgetConfig } from "@/components/dashboard/types";

function isPublished(d: Dashboard): boolean {
  return d.status.toLowerCase() === "published";
}

function Thumb({ dashboard }: { dashboard: Dashboard }) {
  const accent = accentFor(String(dashboard.id));
  const heights = [40, 64, 52, 72, 48, 80, 56, 68];
  return (
    <div className="flex h-32 items-end gap-1.5 rounded-md bg-bg-secondary p-4">
      {heights.map((h, i) => (
        <div
          key={i}
          className="flex-1 rounded-sm"
          style={{
            height: `${h}%`,
            background: i % 2 === 0 ? accent : `${accent}55`,
          }}
        />
      ))}
    </div>
  );
}

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
  const queryClient = useQueryClient();
  const rows = useMemo(() => data ?? [], [data]);
  const [viewingId, setViewingId] = useState<number | null>(
    dashboardId ? Number(dashboardId) : null,
  );
  const viewing = rows.find((d) => d.id === viewingId) ?? null;
  const [aiOpen, setAiOpen] = useState(false);
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

  const createMutation = useMutation({
    mutationFn: () =>
      apiClient.post<Dashboard>(`/api/projects/${projectId}/dashboards`, {
        name: `Dashboard ${rows.length + 1}`,
        description: "",
        config: { widgets: [], globalFilters: [] },
      }),
    onSuccess: async (newDash) => {
      draftIdRef.current = newDash.id;
      await queryClient.invalidateQueries({
        queryKey: ["project", projectId, "dashboards"],
      });
      setViewingId(newDash.id);
    },
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
      if (
        typeof window !== "undefined" &&
        !window.confirm(`Delete dashboard "${d.name}"? This cannot be undone.`)
      ) {
        return;
      }
      if (draftIdRef.current === d.id) draftIdRef.current = null;
      deleteMutation.mutate(d.id);
    },
    [deleteMutation],
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

  const published = rows.filter(isPublished).length;
  const aiCount = rows.filter((d) => d.ai_generated).length;
  const totalViews = rows.reduce((a, d) => a + (d.view_count ?? 0), 0);
  const totalWidgets = rows.reduce((a, d) => a + widgetCount(d.config), 0);

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-dashboards"
      breadcrumbLabel="Dashboards"
      actions={
        <>
          <Button variant="secondary" onClick={() => setAiOpen(true)}>
            <IconSparkles size={14} />
            Generate with AI
          </Button>
          <Button
            variant="primary"
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
          >
            <IconPlus size={14} />
            {createMutation.isPending ? "Creating…" : "New dashboard"}
          </Button>
        </>
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
        />
      ) : (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile
            label="Total dashboards"
            value={rows.length}
            hint={`${published} published`}
          />
          <StatTile
            label="AI-generated"
            value={aiCount}
            hint={`${rows.length - aiCount} manual`}
          />
          <StatTile label="Total views" value={totalViews} />
          <StatTile
            label="Widgets total"
            value={totalWidgets}
            hint="across all dashboards"
          />
        </div>

        {isLoading ? (
          <div className="py-16 text-center text-small text-ink-tertiary">
            Loading dashboards…
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((d) => {
              const pub = isPublished(d);
              return (
                <Card
                  key={d.id}
                  onClick={() => setViewingId(d.id)}
                  className="flex cursor-pointer flex-col overflow-hidden transition-colors hover:border-line-secondary"
                >
                  <div className="p-3">
                    <Thumb dashboard={d} />
                  </div>
                  <div className="flex-1 px-4 pb-3">
                    <div className="text-h3 text-ink-primary">{d.name}</div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Badge tone={pub ? "success" : "outline"}>
                        {pub ? "Published" : "Draft"}
                      </Badge>
                      <Badge tone={d.ai_generated ? "ai" : "neutral"}>
                        {d.ai_generated ? "AI" : "Manual"}
                      </Badge>
                      <span className="text-small text-ink-tertiary">
                        {d.view_count} views
                      </span>
                      <span className="text-small text-ink-tertiary">
                        {widgetCount(d.config)} widgets
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center justify-between border-t border-line-tertiary px-4 py-2.5">
                    <span className="text-small text-ink-tertiary">
                      Updated {timeAgo(d.updated_at)}
                    </span>
                    <div className="flex items-center gap-3 text-[12px] font-medium text-brand-700">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setViewingId(d.id);
                        }}
                        className="hover:underline"
                      >
                        {pub ? "Share" : "Publish"}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setViewingId(d.id);
                        }}
                        className="hover:underline"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        title="Delete dashboard"
                        aria-label={`Delete dashboard ${d.name}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteDashboard(d);
                        }}
                        className="text-ink-tertiary hover:text-red-600"
                      >
                        <IconTrash size={15} />
                      </button>
                    </div>
                  </div>
                </Card>
              );
            })}

            <button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending}
              className={cn(
                "flex min-h-[220px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line-secondary bg-bg-primary text-center hover:border-brand-500 hover:bg-brand-50/40 disabled:opacity-60",
              )}
            >
              <IconLayoutDashboard size={22} className="text-ink-tertiary" />
              <span className="text-h3 text-ink-secondary">
                {createMutation.isPending ? "Creating…" : "New dashboard"}
              </span>
              <span className="max-w-[200px] text-small text-ink-tertiary">
                Build manually or let AI generate from your queries
              </span>
            </button>
          </div>
        )}
      </div>
      )}
      <AIDashboardSuggestionsModal
        open={aiOpen}
        projectId={projectId}
        onClose={() => setAiOpen(false)}
        onSaved={(id) => {
          setAiOpen(false);
          queryClient.invalidateQueries({
            queryKey: ["project", projectId, "dashboards"],
          });
          setViewingId(id);
        }}
        notify={push}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}
