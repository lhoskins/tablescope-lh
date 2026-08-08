"use client";


import { useCallback, useState } from "react";
import {
  IconChartHistogram,
  IconLayoutDashboard,
  IconBulb,
  IconCheck,
  IconLoader2,
  IconDeviceFloppy,
  IconPlayerPlay,
  IconSparkles,
  IconArrowUp,
} from "@tabler/icons-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/api-client";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import {
  suggestQueries,
  suggestDashboards,
  suggestInsights,
  saveDashboardSuggestion,
  type QuerySuggestionsProject,
  type DashboardSuggestionsProject,
  type ProjectResult,
  type InsightCard,
} from "@/lib/api/home-intelligence";
import type {
  GovernanceItem,
  InsightFeedbackRecord,
} from "@/lib/api/insight-feedback";
import {
  IntelligenceCard,
  InsightChartBlock,
} from "@/components/tablescope/home/intelligence-card";
import { QuerySuggestionPreviewModal } from "@/components/tablescope/home/query-suggestion-preview-modal";
import { getDefaultOptions } from "@/lib/visualizations/chartRegistry";import { ProjectHeader } from "./project-header";



export function DashboardSuggestionCard({
  project,
  showProjectHeader = true,
}: {
  project: DashboardSuggestionsProject;
  showProjectHeader?: boolean;
}) {
  const dashboard = project.dashboard!;
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setState("saving");
    setErr(null);
    try {
      await saveDashboardSuggestion({
        project_id: Number(project.projectId),
        title: dashboard.title,
        widgets: dashboard.widgets.map((w) => ({
          title: w.title,
          sql: w.sql,
          chartType: w.chartType,
          labelColumn: w.labelColumn,
          valueColumn: w.valueColumn,
          visualizationOptions: getDefaultOptions(w.chartType),
        })),
      });
      setState("saved");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
      setState("idle");
    }
  };

  return (
    <section className="rounded-lg border border-line-tertiary bg-bg-primary p-4">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          {showProjectHeader && (
            <ProjectHeader
              name={project.projectName}
              color={project.projectColor}
            />
          )}
          <p className="text-small text-ink-secondary">{dashboard.title}</p>
        </div>
        <button
          type="button"
          onClick={() => void save()}
          disabled={state !== "idle"}
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1 text-small font-medium transition-colors",
            state === "saved"
              ? "border-success/40 bg-success/10 text-success"
              : "border-line-secondary text-ink-secondary hover:border-brand-100 hover:text-brand-700 disabled:opacity-50",
          )}
        >
          {state === "saved" ? (
            <>
              <IconCheck size={14} /> Saved
            </>
          ) : state === "saving" ? (
            <>
              <IconLoader2 size={14} className="animate-spin" /> Saving…
            </>
          ) : (
            <>
              <IconDeviceFloppy size={14} /> Save dashboard
            </>
          )}
        </button>
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {dashboard.widgets.map((w, i) => (
          <div
            key={i}
            className="rounded-md border border-line-tertiary bg-bg-secondary/40 p-3"
          >
            <div className="mb-2 text-small font-medium text-ink-primary">
              {w.title}
            </div>
            <InsightChartBlock chart={w.chart} />
          </div>
        ))}
      </div>
      {err && <p className="mt-2 text-small text-danger">{err}</p>}
    </section>
  );
}