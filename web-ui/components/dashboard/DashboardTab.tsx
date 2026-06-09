"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { Dashboard, DashboardConfig } from "./types";
import { CreateDashboardWizard } from "./CreateDashboardWizard";
import { DashboardViewer } from "./DashboardViewer";
import { AIPromptBar } from "@/components/ai/AIPromptBar";

type SavedQuery = { id: number; name: string; sql_text: string | null };
type Datasource = { viewName: string; fileName: string };

type Props = {
  projectId: number;
  savedQueries: SavedQuery[];
  datasources: Datasource[];
  canEdit: boolean;
};

const STATUS_BADGE: Record<string, { cls: string; label: string }> = {
  draft: { cls: "bg-purple-100 text-purple-700", label: "Draft" },
  live: { cls: "bg-blue-100 text-blue-700", label: "Live" },
  published: { cls: "bg-green-100 text-green-700", label: "Published" },
};

export function DashboardTab({ projectId, savedQueries, datasources, canEdit }: Props) {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [viewing, setViewing] = useState<Dashboard | null>(null);
  const [aiDashLoading, setAiDashLoading] = useState(false);
  const [aiDashError, setAiDashError] = useState<string | null>(null);
  const [aiDashSuccess, setAiDashSuccess] = useState<string | null>(null);

  const handleAIGenerateDashboard = useCallback(async (prompt: string) => {
    setAiDashLoading(true);
    setAiDashError(null);
    setAiDashSuccess(null);
    try {
      const result = await apiClient.post<{ dashboard_id: number; dashboard_name: string; widgets_created: number }>(
        "/api/ai/actions/generate-and-save-dashboard",
        { project_id: projectId, prompt },
      );
      setAiDashSuccess(`Dashboard created: ${result.dashboard_name} (${result.widgets_created} widgets)`);
      queryClient.invalidateQueries({ queryKey: ["project-dashboards", projectId] });
    } catch (err) {
      setAiDashError(err instanceof Error ? err.message : "AI dashboard generation failed");
    } finally {
      setAiDashLoading(false);
    }
  }, [projectId, queryClient]);

  const { data: dashboards = [], isLoading } = useQuery<Dashboard[]>({
    queryKey: ["project-dashboards", projectId],
    queryFn: () => apiClient.get<Dashboard[]>(`/api/projects/${projectId}/dashboards`),
  });

  const createMutation = useMutation({
    mutationFn: (payload: { name: string; description: string; config: DashboardConfig }) =>
      apiClient.post<Dashboard>(`/api/projects/${projectId}/dashboards`, payload),
    onSuccess: (newDash) => {
      queryClient.invalidateQueries({ queryKey: ["project-dashboards", projectId] });
      setCreating(false);
      setViewing(newDash);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete(`/api/projects/${projectId}/dashboards/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-dashboards", projectId] });
    },
  });

  // Viewing a dashboard
  if (viewing) {
    const freshDash = dashboards.find((d) => d.id === viewing.id) ?? viewing;
    return (
      <DashboardViewer
        dashboard={freshDash}
        projectId={projectId}
        savedQueries={savedQueries}
        datasources={datasources}
        onBack={() => setViewing(null)}
      />
    );
  }

  // Creating a dashboard
  if (creating) {
    return (
      <CreateDashboardWizard
        projectId={projectId}
        savedQueries={savedQueries}
        datasources={datasources}
        onCancel={() => setCreating(false)}
        onSubmit={(payload) => createMutation.mutate(payload)}
        isSubmitting={createMutation.isPending}
      />
    );
  }

  // Dashboard list
  return (
    <div>
      {canEdit && (
        <div className="mb-4 flex items-start gap-4">
          <button
            onClick={() => setCreating(true)}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 whitespace-nowrap"
          >
            + Create Dashboard
          </button>
          <div className="flex-1">
            <AIPromptBar
              placeholder="Describe the dashboard you want to generate…"
              submitLabel="Generate Dashboard"
              onSubmit={handleAIGenerateDashboard}
              loading={aiDashLoading}
            />
            {aiDashError && (
              <div className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{aiDashError}</div>
            )}
            {aiDashSuccess && (
              <div className="mt-2 rounded-md bg-green-50 px-3 py-2 text-xs text-green-700">{aiDashSuccess}</div>
            )}
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="py-8 text-center text-sm text-slate-400">Loading dashboards…</div>
      ) : dashboards.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed border-slate-200 py-16 text-center">
          <div className="text-4xl">📊</div>
          <h3 className="mt-2 text-sm font-semibold text-slate-700">No dashboards yet</h3>
          <p className="mt-1 text-xs text-slate-500">
            Create a dashboard to visualize your project&apos;s data with charts and widgets.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          {dashboards.map((dash, i) => {
            const badge = STATUS_BADGE[dash.status] ?? STATUS_BADGE.draft;
            const widgetCount = dash.config?.widgets?.length ?? 0;
            return (
              <div
                key={dash.id}
                className={`flex items-center justify-between px-5 py-4 transition-colors hover:bg-slate-50 ${
                  i < dashboards.length - 1 ? "border-b border-slate-100" : ""
                }`}
              >
                <div
                  className="flex-1 cursor-pointer"
                  onClick={() => setViewing(dash)}
                >
                  <div className="font-semibold text-slate-900 text-sm">{dash.name}</div>
                  <div className="mt-0.5 text-xs text-slate-400">
                    {widgetCount} widget{widgetCount !== 1 ? "s" : ""} ·{" "}
                    Updated {new Date(dash.updated_at).toLocaleDateString()}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-semibold ${badge.cls}`}>
                    {badge.label}
                  </span>
                  {canEdit && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`Delete dashboard "${dash.name}"?`)) {
                          deleteMutation.mutate(dash.id);
                        }
                      }}
                      className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-500"
                      title="Delete"
                    >
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                  <span
                    onClick={() => setViewing(dash)}
                    className="cursor-pointer text-lg text-slate-300"
                  >
                    →
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
