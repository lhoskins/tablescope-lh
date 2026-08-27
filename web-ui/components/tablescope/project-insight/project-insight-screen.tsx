"use client";


import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IconHelpCircle, IconSparkles } from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { formatLastUpdated } from "@/lib/format-datetime";
import { IntelligenceWorkspace } from "@/components/tablescope/insights/intelligence-workspace";
import { SaveInsightToDashboardModal } from "@/components/tablescope/home/save-insight-to-dashboard-modal";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";
import { createHomePin, getHomePins } from "@/lib/api/home-pins";
import { suggestInsights, type InsightCard } from "@/lib/api/home-intelligence";

import { projectInsightApi, type ProjectInsight } from "@/lib/api/project-insight";
import {
  CreateActionFromInsightDialog,
  type ActionableInsight,
} from "@/components/tablescope/project-actions/create-action-from-insight-dialog";
import { INSIGHT_KEY } from "./project-insight-screen/insight-key";
import { EMPTY_PROJECT_INSIGHT } from "./project-insight-screen/empty-project-insight";
import { cardToActionableInsight } from "./project-insight-screen/card-to-actionable-insight";
import { LoadingState } from "./project-insight-screen/loading-state";
import { EmptyState } from "./project-insight-screen/empty-state";



export function ProjectInsightScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { toasts, push, dismiss } = useToasts();
  const [granularity, setGranularity] = useState(3);

  const projectIdNum = Number(projectId);

  const { data: homePins = [] } = useQuery({
    queryKey: ["home-pins"],
    queryFn: getHomePins,
  });

  const pinnedByFingerprint = useMemo(() => {
    const map = new Map<string, number>();
    for (const pin of homePins) {
      const payload = (pin.frozen_payload ?? pin.config ?? {}) as {
        evidenceFingerprint?: { resultFingerprint?: string };
        insightId?: string;
      };
      const key =
        payload.evidenceFingerprint?.resultFingerprint ??
        payload.insightId ??
        pin.pin_key;
      if (key) map.set(String(key), pin.id);
    }
    return map;
  }, [homePins]);

  const pinMutation = useMutation({
    mutationFn: createHomePin,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["home-pins"] });
      push("Pinned to Home", "success");
    },
    onError: (err: Error) => push(err.message, "error"),
  });

  const handlePinInsight = useCallback(
    (card: InsightCard) => {
      const key =
        card.evidenceFingerprint?.resultFingerprint ??
        card.insightId ??
        card.id;
      if (!key) {
        push("Unable to pin this insight", "error");
        return;
      }
      if (pinnedByFingerprint.has(key)) {
        push("This insight is already pinned to Home", "info");
        return;
      }
      pinMutation.mutate({
        pin_type: "insight_card",
        pin_key: `insight:${card.projectId}:${card.insightType}:${key}`,
        destination: "home",
        title: card.title,
        project_id: Number(card.projectId),
        frozen_payload: card as unknown as Record<string, unknown>,
        layout: { x: 0, y: 0, w: 6, h: 5 },
      });
    },
    [pinMutation, pinnedByFingerprint, push],
  );

  const [saveToDashboardCard, setSaveToDashboardCard] = useState<InsightCard | null>(null);
  const [createActionOpen, setCreateActionOpen] = useState(false);
  const [selectedInsight, setSelectedInsight] = useState<ActionableInsight | null>(null);

  const handleCreateAction = useCallback((card: InsightCard) => {
    setSelectedInsight(cardToActionableInsight(card));
    setCreateActionOpen(true);
  }, []);

  const {
    data: rawData,
    isLoading,
    isFetching,
    isError,
  } = useQuery<ProjectInsight>({
    queryKey: INSIGHT_KEY(projectId),
    queryFn: () => projectInsightApi.get(projectId),
    staleTime: 5 * 60_000,
    refetchInterval: (query) => {
      const latest = query.state.data as ProjectInsight | undefined;
      return latest?.stale ? 5_000 : false;
    },
  });

  const insight = rawData ?? EMPTY_PROJECT_INSIGHT;

  const refresh = useMutation({
    mutationFn: () => projectInsightApi.refresh(projectId),
    onSuccess: (fresh) => {
      queryClient.setQueryData(INSIGHT_KEY(projectId), fresh);
    },
    onError: (err: Error) => push(err.message, "error"),
  });

  const insightsQuery = useQuery({
    queryKey: [...INSIGHT_KEY(projectId), "suggested-insights", granularity],
    queryFn: () => suggestInsights(granularity, projectIdNum),
    staleTime: 5 * 60_000,
    enabled: !Number.isNaN(projectIdNum),
  });

  // suggestInsights (GET-or-generate) returns the cached ProjectIntelligenceSnapshot
  // ("insights" suite) whenever one already exists -- it never re-runs analysis on
  // its own. insightsQuery.refetch() just re-issues that same cache-first call, so
  // without the explicit refresh flag the Analyze button and the Depth control both
  // silently returned the SAME (possibly stale or empty) snapshot every time,
  // regardless of how many times they were clicked. This mutation is the only path
  // that actually asks the backend to regenerate.
  const analyzeInsights = useMutation({
    mutationFn: (g: number) => suggestInsights(g, projectIdNum, true),
    onSuccess: (data, g) => {
      queryClient.setQueryData(
        [...INSIGHT_KEY(projectId), "suggested-insights", g],
        data,
      );
    },
    onError: (err: Error) => push(err.message, "error"),
  });

  const clearCache = useMutation({
    mutationFn: () => projectInsightApi.clearCache(projectId),
    onSuccess: (fresh) => {
      // The server marks the snapshot stale and queues a rebuild, so the
      // page shows the existing insight with a "reloading" indicator instead
      // of going blank while the rebuild runs.
      queryClient.setQueryData(INSIGHT_KEY(projectId), fresh);
      queryClient.removeQueries({ queryKey: ["percent-change-summary"] });
      // clear-cache only clears the executive-summary ("project_insight")
      // snapshot server-side, not the insight cards ("insights") snapshot --
      // force those to regenerate too, the same as the Analyze button.
      analyzeInsights.mutate(granularity);
      push("Project Insight cache cleared", "success");
    },
    onError: (err: Error) => push(err.message, "error"),
  });

  const handleClearCache = () => {
    if (
      !window.confirm(
        "Clear cached Project Insight cards and the Percent Change Summary?",
      )
    ) return;
    clearCache.mutate();
  };

  const handleRefresh = () => {
    refresh.mutate();
    analyzeInsights.mutate(granularity);
  };

  const handleGranularity = (value: number) => {
    setGranularity(value);
    analyzeInsights.mutate(value);
  };

  const allInsightCards = useMemo(
    () =>
      insightsQuery.data?.projects
        ?.filter((project) => Number(project.projectId) === projectIdNum)
        .flatMap((project) => project.insights) ?? [],
    [insightsQuery.data, projectIdNum],
  );

  const insightIds = useMemo(
    () => allInsightCards.map((c) => c.insightId || c.id).filter(Boolean),
    [allInsightCards],
  );

  const {
    feedbackById,
    governanceById,
    saveFeedback,
    removeFeedback,
    respondToReview,
    saving: savingFeedback,
  } = useInsightFeedback(insightIds, Number.isNaN(projectIdNum) ? undefined : projectIdNum);

  const handleFeedbackSave = useCallback(
    (
      card: InsightCard,
      payload: {
        sentiment: "agree" | "disagree";
        reason_codes: string[];
        comment: string;
      },
    ) => {
      const insightId = card.insightId || card.id;
      if (!insightId) return;
      void saveFeedback({
        insightId,
        projectId: projectIdNum,
        insightType: card.insightType,
        sentiment: payload.sentiment,
        reason_codes: payload.reason_codes,
        comment: payload.comment,
        cardSnapshot: card as unknown as Record<string, unknown>,
        explanationSnapshot: card.explanation as Record<string, unknown> | undefined,
      });
    },
    [saveFeedback, projectIdNum],
  );

  const handleFeedbackRemove = useCallback(
    (card: InsightCard) => {
      const insightId = card.insightId || card.id;
      if (!insightId) return;
      void removeFeedback({ insightId, projectId: projectIdNum });
    },
    [removeFeedback, projectIdNum],
  );

  const handleFeedbackRespond = useCallback(
    (card: InsightCard, response: string) => {
      const insightId = card.insightId || card.id;
      if (!insightId) return;
      void respondToReview({ insightId, response });
    },
    [respondToReview],
  );

  const running =
    refresh.isPending ||
    isFetching ||
    insightsQuery.isFetching ||
    analyzeInsights.isPending;

  const lastUpdated = useMemo(
    () => (insight.lastUpdatedAt ? new Date(insight.lastUpdatedAt) : null),
    [insight.lastUpdatedAt],
  );

  const handleSaveToDashboard = useCallback((card: InsightCard) => {
    setSaveToDashboardCard(card);
  }, []);

  const handleSaved = useCallback(
    (_dashboardId: number, dashboardName: string) => {
      push(`Saved to dashboard "${dashboardName}"`, "success");
      setSaveToDashboardCard(null);
    },
    [push],
  );

  const intelligenceToolbar = {
    projectCount: 1,
    totalProjectCount: 1,
    running,
    lastUpdatedLabel: formatLastUpdated(lastUpdated),
    onRefresh: handleRefresh,
    onClearCache: handleClearCache,
    isClearingCache: clearCache.isPending,
    granularity,
    onGranularityChange: handleGranularity,
    availableProjects: [],
    selectedProjectIds: new Set([projectId]),
    onToggleProject: () => {},
    onSelectAll: () => {},
    onClear: () => {},
  };

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-insights"
      breadcrumbLabel="Project Insight"
      showResourceTabs={false}
      assistantSurface="project_insights"
      assistantContextLabel="Project Insights"
      actions={
        <>
          <StatusDot tone="online" className="mr-1" />
          <Button
            variant="secondary"
            size="md"
            onClick={() => router.push("/help")}
          >
            <IconHelpCircle size={15} />
            Help
          </Button>
        </>
      }
    >
      <div className="space-y-6 pb-24">
        {isLoading ? (
          <div className="mx-auto w-full max-w-content py-4">
            <LoadingState />
          </div>
        ) : isError ? (
          <div className="mx-auto w-full max-w-content py-4">
            <EmptyState
              title="Couldn't load Project Insight"
              body="Something went wrong building this project's insight. Try refreshing."
            />
          </div>
        ) : (
          <IntelligenceWorkspace
            scope="project"
            presentation="executive"
            projectIds={[projectIdNum]}
            cards={allInsightCards}
            running={running}
            lastUpdated={lastUpdated}
            snapshotFingerprint={insight.lastUpdatedAt ?? null}
            toolbar={intelligenceToolbar}
            actions={{
              onSaveToDashboard: handleSaveToDashboard,
              onPin: handlePinInsight,
              onCreateAction: handleCreateAction,
              onFeedbackSave: handleFeedbackSave,
              onFeedbackRemove: handleFeedbackRemove,
              onFeedbackRespond: handleFeedbackRespond,
            }}
            feedback={{ feedbackById, savingFeedback, governanceById }}
            pinnedByFingerprint={pinnedByFingerprint}
            emptyMessages={{
              risks: "No risks detected from this project's data yet.",
              trends: "No trends detected from this project's data yet.",
              opportunities:
                "No opportunities detected from this project's data yet.",
              analysis: "No deeper analysis available for this project yet.",
            }}
            actionsDisclosure="collapsible"
            header={
              <div>
                <div className="mb-1.5 flex items-center gap-2 text-caption font-medium uppercase tracking-wide text-ink-tertiary">
                  <IconSparkles size={14} className="text-brand-500" />
                  Executive perspective · AI briefing
                </div>
                <h1 className="text-h1 text-ink-primary">Project Insights</h1>
                <p className="mt-1 text-body text-ink-tertiary">
                  Material changes across {insight.project.name || "this project"}&apos;s data and documents.
                </p>
              </div>
            }
          />
        )}
      </div>

      <CreateActionFromInsightDialog
        open={createActionOpen}
        onClose={() => setCreateActionOpen(false)}
        insight={selectedInsight}
      />

      {saveToDashboardCard && (
        <SaveInsightToDashboardModal
          card={saveToDashboardCard}
          open={Boolean(saveToDashboardCard)}
          onClose={() => setSaveToDashboardCard(null)}
          onSaved={handleSaved}
        />
      )}

      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}
