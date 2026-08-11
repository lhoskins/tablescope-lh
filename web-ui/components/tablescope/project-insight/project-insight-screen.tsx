"use client";


import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconAlertCircle,
  IconChevronRight,
  IconHelpCircle,
  IconLoader2,
  IconSparkles,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { formatLastUpdated } from "@/lib/format-datetime";
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import { IntelligenceWorkspace } from "@/components/tablescope/insights/intelligence-workspace";
import { IntelligenceStrip } from "@/components/tablescope/home/intelligence-strip";
import { ExecutiveProjectSummary } from "@/components/tablescope/project-insight/executive-project-summary";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import { SaveInsightToDashboardModal } from "@/components/tablescope/home/save-insight-to-dashboard-modal";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";
import { createHomePin, getHomePins } from "@/lib/api/home-pins";
import { suggestInsights, type InsightCard } from "@/lib/api/home-intelligence";

import { projectInsightApi, type ProjectInsight } from "@/lib/api/project-insight";
import {
  getConversation,
  submitCanonicalTurn,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";
import { buildAiAssistantHref } from "@/lib/navigation/ai-assistant";
import {
  CreateActionFromInsightDialog,
  type ActionableInsight,
} from "@/components/tablescope/project-actions/create-action-from-insight-dialog";import { INSIGHT_KEY } from "./project-insight-screen/insight-key";
import { EMPTY_PROJECT_INSIGHT } from "./project-insight-screen/empty-project-insight";
import { cardToActionableInsight } from "./project-insight-screen/card-to-actionable-insight";
import { LoadingState } from "./project-insight-screen/loading-state";
import { EmptyState } from "./project-insight-screen/empty-state";
import { pollConversation } from "./project-insight-screen/poll-conversation";



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

  const clearCache = useMutation({
    mutationFn: () => projectInsightApi.clearCache(projectId),
    onSuccess: (fresh) => {
      // The server marks the snapshot stale and queues a rebuild, so the
      // page shows the existing insight with a "reloading" indicator instead
      // of going blank while the rebuild runs.
      queryClient.setQueryData(INSIGHT_KEY(projectId), fresh);
      insightsQuery.refetch();
      push("Project Insight cache cleared", "success");
    },
    onError: (err: Error) => push(err.message, "error"),
  });

  const handleClearCache = () => {
    if (!window.confirm("Clear cached Project Insight cards?")) return;
    clearCache.mutate();
  };

  const insightsQuery = useQuery({
    queryKey: [...INSIGHT_KEY(projectId), "suggested-insights", granularity],
    queryFn: () => suggestInsights(granularity, projectIdNum),
    staleTime: 5 * 60_000,
    enabled: !Number.isNaN(projectIdNum),
  });

  const handleRefresh = () => {
    refresh.mutate();
    insightsQuery.refetch();
  };

  const handleGranularity = (value: number) => {
    setGranularity(value);
    insightsQuery.refetch();
  };

  const allInsightCards = useMemo(
    () => insightsQuery.data?.projects?.flatMap((p) => p.insights) ?? [],
    [insightsQuery.data],
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

  // Project-scoped Ask Anything conversation, persisted under "Project Insights".
  const [chatConversationId, setChatConversationId] = useState<number | null>(null);
  const [chatTurns, setChatTurns] = useState<ConversationTurn[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatPending, setChatPending] = useState<string | null>(null);

  const handleProjectAsk = useCallback(
    async (message: string) => {
      setChatBusy(true);
      setChatError(null);
      setChatPending(message);
      const requestId = crypto.randomUUID();
      try {
        const res = await submitCanonicalTurn({
          surface: "project_insights",
          project_id: projectIdNum,
          message,
          client_request_id: requestId,
        });
        setChatConversationId(res.conversation_id);
        setChatTurns((prev) => {
          const exists = prev.some((t) => t.id === res.turn.id);
          return exists ? prev : [...prev, res.turn];
        });
        if (res.turn.status === "pending") {
          const polled = await pollConversation(res.conversation_id);
          const updated = polled.turns.find((t) => t.id === res.turn.id) ??
            polled.turns[polled.turns.length - 1];
          setChatTurns((prev) =>
            prev.map((t) => (t.id === updated.id ? updated : t))
          );
        }
      } catch (err) {
        setChatError(err instanceof Error ? err.message : "Ask failed");
      } finally {
        setChatBusy(false);
        setChatPending(null);
      }
    },
    [projectIdNum],
  );

  const openInAssistant = () => {
    if (chatConversationId == null) return;
    router.push(
      buildAiAssistantHref({
        conversationId: chatConversationId,
        projectId: projectIdNum,
      })
    );
  };

  const analysisChildren = useMemo(() => {
    const questions = (insight.questionsToAsk ?? []).filter((q) =>
      q.question?.trim(),
    );
    const needing = (insight.questionsNeedingData ?? []).filter((q) =>
      (q.question || q.businessQuestion || q.title)?.trim(),
    );
    if (questions.length === 0 && needing.length === 0) return null;

    return (
      <div className="space-y-4 rounded-lg border border-line-tertiary bg-bg-primary p-4">
        {questions.length > 0 && (
          <div>
            <h3 className="mb-2 flex items-center gap-2 text-h3 text-ink-primary">
              <IconHelpCircle size={16} className="text-brand-500" />
              AI-Generated Questions to Ask
            </h3>
            <ul className="divide-y divide-line-tertiary">
              {questions.map((q) => (
                <li key={q.id}>
                  <button
                    type="button"
                    onClick={() => handleProjectAsk(q.question)}
                    className="flex w-full items-center justify-between gap-3 py-2.5 text-left text-[13px] text-ink-secondary hover:text-brand-700"
                  >
                    <span>{q.question}</span>
                    <IconChevronRight
                      size={15}
                      className="shrink-0 text-ink-tertiary"
                    />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {needing.length > 0 && (
          <div className={questions.length > 0 ? "border-t border-line-tertiary pt-3" : ""}>
            <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-ink-tertiary">
              <IconAlertCircle size={14} className="text-warning" />
              Needs additional data
            </div>
            <ul className="space-y-2">
              {needing.map((q, i) => {
                const text = q.question || q.businessQuestion || q.title || "";
                return (
                  <li
                    key={q.id ?? `${text}-${i}`}
                    className="rounded-md bg-bg-secondary px-2.5 py-2 text-[13px]"
                  >
                    <div className="text-ink-secondary">{text}</div>
                    {q.missingDataHint && (
                      <div className="mt-1 text-[12px] text-ink-tertiary">
                        {q.missingDataHint}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    );
  }, [insight.questionsToAsk, insight.questionsNeedingData, handleProjectAsk]);

  const running = refresh.isPending || isFetching || insightsQuery.isFetching;

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

  const cardActions = useMemo(
    () => ({
      onPin: handlePinInsight,
      onSaveToDashboard: handleSaveToDashboard,
      onCreateAction: handleCreateAction,
      onFeedbackSave: handleFeedbackSave,
      onFeedbackRemove: handleFeedbackRemove,
      onFeedbackRespond: handleFeedbackRespond,
      feedbackById,
      savingFeedback,
      governanceById,
      pinnedByFingerprint,
      actionsDisclosure: "collapsible" as const,
    }),
    [
      handlePinInsight,
      handleSaveToDashboard,
      handleCreateAction,
      handleFeedbackSave,
      handleFeedbackRemove,
      handleFeedbackRespond,
      feedbackById,
      savingFeedback,
      governanceById,
      pinnedByFingerprint,
    ],
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
    >
      <div className="mx-auto w-full max-w-content space-y-6 py-4">
        {isLoading ? (
          <LoadingState />
        ) : isError ? (
          <EmptyState
            title="Couldn't load Project Insight"
            body="Something went wrong building this project's insight. Try refreshing."
          />
        ) : (
          <>
            <HomeAiSuggestions
              projectId={projectIdNum}
              showAskBox
              onAsk={handleProjectAsk}
              cardActions={cardActions}
            />

            {((chatTurns.length > 0) || chatBusy || chatError || chatPending) && (
              <div className="space-y-4 rounded-xl border border-line-tertiary bg-bg-primary p-4">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-h3 text-ink-primary">Ask Anything</h3>
                  {chatConversationId && (
                    <Button variant="ghost" size="sm" onClick={openInAssistant}>
                      Open in AI Assistant
                    </Button>
                  )}
                </div>
                <div className="max-h-[30rem] space-y-4 overflow-y-auto">
                  {chatTurns.map((t, i) => (
                    <TurnBubble
                      key={t.id}
                      turn={t}
                      isLast={i === chatTurns.length - 1}
                      onFollowUp={handleProjectAsk}
                    />
                  ))}
                  {chatPending && (
                    <div className="flex justify-end">
                      <div className="max-w-[80%] rounded-lg bg-brand px-3.5 py-2.5 text-[13px] leading-relaxed text-brand-fg">
                        {chatPending}
                      </div>
                    </div>
                  )}
                  {chatBusy && (
                    <div className="flex items-center gap-2 text-small text-ink-tertiary">
                      <IconLoader2 size={16} className="animate-spin" />
                      TableScope is thinking…
                    </div>
                  )}
                  {chatError && (
                    <p className="text-small text-danger">{chatError}</p>
                  )}
                </div>
              </div>
            )}

            <IntelligenceStrip {...intelligenceToolbar} scope="project" />
            <ExecutiveProjectSummary summary={insight.executiveSummary} />

            <IntelligenceWorkspace
              scope="project"
              projectIds={[projectIdNum]}
              cards={allInsightCards}
              running={running}
              lastUpdated={lastUpdated}
              snapshotFingerprint={insight.lastUpdatedAt ?? null}
              toolbar={intelligenceToolbar}
              showToolbar={false}
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
              analysisChildren={analysisChildren}
            />
          </>
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
