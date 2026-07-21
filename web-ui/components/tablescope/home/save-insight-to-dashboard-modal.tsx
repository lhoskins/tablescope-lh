"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  IconX,
  IconLoader2,
  IconDeviceFloppy,
  IconCheck,
  IconFolderPlus,
  IconLayoutDashboard,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import {
  saveCardToDashboard,
  type InsightCard,
  type SaveCardToDashboardPayload,
} from "@/lib/api/home-intelligence";

interface DashboardListItem {
  id: number;
  name: string;
  project_id: number;
  updated_at: string;
}

export function SaveInsightToDashboardModal({
  card,
  open,
  onClose,
  onSaved,
}: {
  card: InsightCard;
  open: boolean;
  onClose: () => void;
  onSaved?: (dashboardId: number, dashboardName: string) => void;
}) {
  const sourceProjectId = String(card.projectId);

  const [mode, setMode] = useState<"existing" | "new">("new");
  const [selectedDashboardId, setSelectedDashboardId] = useState<number | null>(null);
  const [newDashboardName, setNewDashboardName] = useState<string>("");
  const [widgetTitle, setWidgetTitle] = useState<string>(card.title || "");
  const [error, setError] = useState<string | null>(null);

  const {
    data: dashboards = [],
    isLoading: dashboardsLoading,
    error: dashboardsError,
  } = useQuery({
    queryKey: ["projects", sourceProjectId, "dashboards"],
    queryFn: async () => {
      const rows = await apiClient.get<DashboardListItem[]>(
        `/api/projects/${sourceProjectId}/dashboards`,
      );
      return rows;
    },
    enabled: !!sourceProjectId,
  });

  useEffect(() => {
    if (!open) return;
    setMode("new");
    setSelectedDashboardId(null);
    setNewDashboardName(`${card.title || "Insight"} Dashboard`.slice(0, 80));
    setWidgetTitle(card.title || "");
    setError(null);
  }, [open, sourceProjectId, card.title]);

  useEffect(() => {
    setSelectedDashboardId(null);
    if (mode === "existing" && dashboards.length > 0) {
      setSelectedDashboardId(dashboards[0].id);
    }
  }, [mode, dashboards]);

  const saveMutation = useMutation({
    mutationFn: (payload: SaveCardToDashboardPayload) => saveCardToDashboard(payload),
    onSuccess: (res) => {
      onSaved?.(res.dashboard_id, res.name);
      onClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  if (!open) return null;

  const canSubmit =
    widgetTitle.trim() &&
    (mode === "existing"
      ? selectedDashboardId !== null
      : newDashboardName.trim().length > 0);

  const handleSave = () => {
    if (!card.sql) return;
    const payload: SaveCardToDashboardPayload = {
      project_id: Number(sourceProjectId),
      source_project_id: Number(sourceProjectId),
      title: widgetTitle.trim(),
      sql: card.sql,
      chartType: card.chartType || "bar",
      labelColumn: card.labelColumn,
      valueColumn: card.valueColumn,
      valueColumn2: card.valueColumn2,
    };
    if (mode === "existing" && selectedDashboardId !== null) {
      payload.dashboard_id = selectedDashboardId;
    } else {
      payload.dashboard_name = newDashboardName.trim();
    }
    setError(null);
    saveMutation.mutate(payload);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4">
      <div className="my-8 w-full max-w-lg rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-h2 text-ink-primary">Save insight to dashboard</h2>
            <p className="mt-1 text-small text-ink-tertiary">
              The insight chart will be added as a live widget backed by its
              underlying query.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="shrink-0 text-ink-tertiary hover:text-ink-primary"
          >
            <IconX size={18} />
          </button>
        </div>

        <div className="space-y-5">
          <div>
            <label className="mb-1.5 block text-small font-medium text-ink-secondary">
              Project
            </label>
            <div className="flex items-center gap-2 rounded-md border border-line-tertiary bg-bg-secondary/50 px-3 py-2 text-[13px] text-ink-primary">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: card.projectColor }}
              />
              {card.projectName}
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-small font-medium text-ink-secondary">
              Widget title
            </label>
            <input
              value={widgetTitle}
              onChange={(e) => setWidgetTitle(e.target.value)}
              placeholder="Widget title"
              className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-small font-medium text-ink-secondary">
              Destination
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setMode("new")}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-md border px-3 py-2 text-[13px] font-medium transition ${
                  mode === "new"
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : "border-line-secondary bg-bg-secondary text-ink-secondary hover:border-line-primary"
                }`}
              >
                <IconFolderPlus size={14} />
                New dashboard
              </button>
              <button
                type="button"
                onClick={() => setMode("existing")}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-md border px-3 py-2 text-[13px] font-medium transition ${
                  mode === "existing"
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : "border-line-secondary bg-bg-secondary text-ink-secondary hover:border-line-primary"
                }`}
              >
                <IconLayoutDashboard size={14} />
                Existing dashboard
              </button>
            </div>
          </div>

          {mode === "new" ? (
            <div>
              <label className="mb-1.5 block text-small font-medium text-ink-secondary">
                New dashboard name
              </label>
              <input
                value={newDashboardName}
                onChange={(e) => setNewDashboardName(e.target.value)}
                placeholder="e.g. Q3 Performance"
                className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
              />
            </div>
          ) : (
            <div>
              <label className="mb-2 block text-small font-medium text-ink-secondary">
                Choose dashboard
              </label>
              {dashboardsLoading ? (
                <div className="flex items-center gap-2 py-3 text-small text-ink-tertiary">
                  <IconLoader2 size={14} className="animate-spin" />
                  Loading dashboards…
                </div>
              ) : dashboardsError ? (
                <p className="text-small text-red-600">
                  Could not load dashboards for this project.
                </p>
              ) : dashboards.length === 0 ? (
                <div className="rounded-md border border-line-tertiary bg-bg-secondary/50 p-3 text-small text-ink-tertiary">
                  No dashboards in this project yet. Switch to “New dashboard” to
                  create one.
                </div>
              ) : (
                <div className="flex max-h-40 flex-wrap gap-2 overflow-y-auto rounded-md border border-line-tertiary bg-bg-secondary/30 p-3">
                  {dashboards.map((d) => {
                    const selected = selectedDashboardId === d.id;
                    return (
                      <button
                        key={d.id}
                        type="button"
                        onClick={() => setSelectedDashboardId(d.id)}
                        className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] transition ${
                          selected
                            ? "border-brand-500 bg-brand-50 text-brand-700"
                            : "border-line-secondary bg-bg-primary text-ink-secondary hover:border-line-primary hover:text-ink-primary"
                        }`}
                      >
                        {selected && <IconCheck size={14} />}
                        {d.name}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-small text-red-800">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleSave}
              disabled={!canSubmit || saveMutation.isPending}
            >
              {saveMutation.isPending ? (
                <>
                  <IconLoader2 size={14} className="animate-spin" /> Saving…
                </>
              ) : (
                <>
                  <IconDeviceFloppy size={14} /> Save widget
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
