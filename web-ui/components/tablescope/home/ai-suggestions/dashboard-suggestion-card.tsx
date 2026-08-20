"use client";

import { useState } from "react";
import { IconSparkles } from "@tabler/icons-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/cn";
import { InsightChartBlock } from "@/components/tablescope/home/intelligence-card";
import { AIDashboardDesigner } from "@/components/tablescope/project/ai-dashboard-designer";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import type { DashboardSuggestionsProject } from "@/lib/api/home-intelligence";
import { ProjectHeader } from "./project-header";

export function DashboardSuggestionCard({
  project,
  showProjectHeader = true,
}: {
  project: DashboardSuggestionsProject;
  showProjectHeader?: boolean;
}) {
  const dashboard = project.dashboard!;
  const [designerOpen, setDesignerOpen] = useState(false);
  const router = useRouter();
  const { toasts, push, dismiss } = useToasts();

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
          onClick={() => setDesignerOpen(true)}
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1 text-small font-medium transition-colors",
            "border-line-secondary text-ink-secondary hover:border-brand-100 hover:text-brand-700",
          )}
        >
          <IconSparkles size={14} />
          Generate with AI
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
      <AIDashboardDesigner
        open={designerOpen}
        projectId={String(project.projectId)}
        mode="create"
        notify={(message, tone) => push(message, tone ?? "info")}
        onClose={() => setDesignerOpen(false)}
        onApplied={(dashboardId) => {
          push("Dashboard created with AI", "success");
          setDesignerOpen(false);
          router.push(`/projects/${project.projectId}/dashboards?dashboard=${dashboardId}`);
        }}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </section>
  );
}
