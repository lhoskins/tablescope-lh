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
import { getDefaultOptions } from "@/lib/visualizations/chartRegistry";import { Pill } from "./ai-suggestions/pill";
import { PILLS } from "./ai-suggestions/pills";
import { HomeAskBox } from "./ai-suggestions/home-ask-box";
import { HomeAiSuggestionsCardActions } from "./ai-suggestions/home-ai-suggestions-card-actions";
import { QuerySuggestionsPanel } from "./ai-suggestions/query-suggestions-panel";
import { DashboardSuggestionsPanel } from "./ai-suggestions/dashboard-suggestions-panel";
import { InsightsPanel } from "./ai-suggestions/insights-panel";



export function HomeAiSuggestions({
  projectId,
  showAskBox,
  onAsk,
  cardActions,
}: {
  /** When set, every suggestion pill generates for this project only and the
   *  per-project section headers are hidden. Omitted, the original Home
   *  behavior (all accessible projects) applies. */
  projectId?: number;
  /** Render the ask input. Defaults to true for Home and false for a project-scoped view. */
  showAskBox?: boolean;
  /** Optional ask handler. When provided, the ask box calls this instead of routing via /api/ai/route-prompt. */
  onAsk?: (prompt: string) => void | Promise<void>;
  cardActions?: HomeAiSuggestionsCardActions;
} = {}) {
  const scoped = projectId != null;
  const askVisible = showAskBox ?? !scoped;
  const [active, setActive] = useState<Pill | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [queryProjects, setQueryProjects] = useState<
    QuerySuggestionsProject[] | null
  >(null);
  const [dashboardProjects, setDashboardProjects] = useState<
    DashboardSuggestionsProject[] | null
  >(null);
  const [insightProjects, setInsightProjects] = useState<
    ProjectResult[] | null
  >(null);

  const run = useCallback(
    async (pill: Pill) => {
      setActive(pill);
      setError(null);
      setLoading(true);
      try {
        if (pill === "queries") {
          const res = await suggestQueries(3, projectId);
          setQueryProjects(res.projects);
        } else if (pill === "dashboards") {
          const res = await suggestDashboards(3, projectId);
          setDashboardProjects(res.projects);
        } else {
          const res = await suggestInsights(3, projectId);
          setInsightProjects(res.projects);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Suggestion failed");
      } finally {
        setLoading(false);
      }
    },
    [projectId],
  );

  return (
    <div className="space-y-4">
      {askVisible && <HomeAskBox projectId={projectId} onAsk={onAsk} />}
      <div className="flex flex-wrap justify-center gap-2">
        {PILLS.map((p) => {
          const Icon = p.icon;
          return (
            <button
              key={p.key}
              type="button"
              onClick={() => void run(p.key)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors",
                active === p.key
                  ? "border-brand-500 bg-brand-50 text-brand-700"
                  : "border-line-secondary bg-bg-primary text-ink-secondary hover:border-brand-100 hover:text-brand-700",
              )}
            >
              <Icon size={15} />
              {p.label}
            </button>
          );
        })}
      </div>

      {active && (
        <div className="mx-auto mt-6 w-full max-w-content">
          {loading && (
            <div className="flex items-center justify-center gap-2 rounded-lg border border-line-tertiary bg-bg-primary py-10 text-small text-ink-tertiary">
              <IconLoader2 size={16} className="animate-spin" />
              {scoped
                ? "Generating for this project…"
                : "Generating across your projects…"}
            </div>
          )}
          {!loading && error && (
            <div className="rounded-lg border border-danger/30 bg-danger/5 p-4 text-small text-danger">
              {error}
            </div>
          )}
          {!loading && !error && active === "queries" && (
            <QuerySuggestionsPanel
              projects={queryProjects ?? []}
              showProjectHeader={!scoped}
            />
          )}
          {!loading && !error && active === "dashboards" && (
            <DashboardSuggestionsPanel
              projects={dashboardProjects ?? []}
              showProjectHeader={!scoped}
            />
          )}
          {!loading && !error && active === "insights" && (
            <InsightsPanel
              projects={insightProjects ?? []}
              showProjectHeader={!scoped}
              cardActions={cardActions}
            />
          )}
        </div>
      )}
    </div>
  );
}
