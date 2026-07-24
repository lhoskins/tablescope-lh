"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconSparkles,
  IconRefresh,
  IconAlertTriangle,
  IconAlertCircle,
  IconArrowUpRight,
  IconBulb,
  IconTrendingUp,
  IconHelpCircle,
  IconCheck,
  IconChevronRight,
  IconSearch,
  IconTable,
  IconFileText,
  IconLoader2,
  IconInfoCircle,
  IconClipboardList,
  IconThumbUp,
  IconThumbDown,
  IconChartBar,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { canManageProjectActions } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { cn } from "@/lib/cn";
import {
  InsightPanel as Panel,
  PanelEmpty,
} from "@/components/tablescope/insight-panel";
import { AIQuestionResultModal } from "@/components/ai/AIQuestionResultModal";
import type { AiCardContext } from "@/lib/api/ai-actions";
import { renderBold } from "@/components/tablescope/home/intelligence-card";
import { InsightsPanel, HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import {
  InsightAnalysisDetails,
  RAnalyticsBadge,
} from "@/components/tablescope/home/insight-engine-badge";
import { ChartSuggestionDialog } from "@/components/tablescope/home/chart-suggestion-dialog";
import {
  InsightExplanationPanel,
} from "@/components/tablescope/home/insight-explanation-panel";
import {
  InsightFeedbackDialog,
} from "@/components/tablescope/home/insight-feedback-dialog";
import {
  InsightFeedbackStatusBadge,
  InsightFeedbackStatusDialog,
  InsightGovernanceBadge,
} from "@/components/tablescope/home/insight-feedback-status";
import {
  CreateActionFromInsightDialog,
  type ActionableInsight,
} from "@/components/tablescope/project-actions/create-action-from-insight-dialog";
import {
  suggestInsights,
  type InsightCard as InsightCardData,
  type InsightExplanation,
} from "@/lib/api/home-intelligence";
import type { GovernanceItem, InsightFeedbackRecord, InsightSentiment } from "@/lib/api/insight-feedback";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";
import { formatLastUpdated } from "@/lib/format-datetime";
import { createHomePin, getHomePins } from "@/lib/api/home-pins";
import {
  projectInsightApi,
  type ProjectInsight,
  type ProjectInsightCard,
  type InsightWorkflowItem,
  type ReviewedInsight,
} from "@/lib/api/project-insight";
import { SUMMARY_TONES, CARD_SEVERITY } from "@/lib/ui/insight-tones";

function cardContextFromCard(card: ProjectInsightCard): AiCardContext {
  return {
    insight_type: card.insightType,
    source_tables: card.sourceTables ?? card.supportingSources,
    source_columns: card.sourceColumns,
    metric: card.metric,
    period_column: card.periodColumn,
  };
}

function toProjectInsightCard(card: InsightCardData): ProjectInsightCard {
  const supporting: string[] = [
    ...(card.sources?.tables ?? []),
    ...(card.sources?.documents ?? []),
  ];
  const severity =
    card.severity === "info" ? "informational" : card.severity;
  return {
    id: card.insightId ?? card.id,
    insightId: card.insightId ?? card.id,
    insightType: card.insightType,
    title: card.title,
    summary: card.summary,
    severity: severity as ProjectInsightCard["severity"],
    recommendedAction: card.callout?.text,
    question: card.question || card.title || card.summary,
    supportingSources: supporting,
    sourceTables: card.sources?.tables,
    explanation: card.explanation as unknown as Record<string, unknown>,
    sql: card.sql,
    chartType: card.chartType,
    labelColumn: card.labelColumn,
    valueColumn: card.valueColumn,
    valueColumn2: card.valueColumn2,
    executedAt: card.executedAt,
  };
}

const INSIGHT_KEY = (projectId: string) => ["project", projectId, "insight"];
const REVIEWED_KEY = (projectId: string) => [
  "project",
  projectId,
  "insight",
  "reviewed",
];

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

export function ProjectInsightScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { toasts, push, dismiss } = useToasts();

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
    (card: InsightCardData) => {
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
        title: card.title,
        project_id: Number(card.projectId),
        frozen_payload: card as unknown as Record<string, unknown>,
        layout: { x: 0, y: 0, w: 6, h: 5 },
      });
    },
    [pinMutation, pinnedByFingerprint, push],
  );

  const [askModal, setAskModal] = useState<{
    open: boolean;
    question: string;
    source: string;
    cardContext?: AiCardContext;
  }>({ open: false, question: "", source: "" });
  const [createActionOpen, setCreateActionOpen] = useState(false);
  const [selectedInsight, setSelectedInsight] = useState<ActionableInsight | null>(null);
  const [loadErrorToasted, setLoadErrorToasted] = useState(false);
  const [refreshErrorToasted, setRefreshErrorToasted] = useState(false);

  const { data, isLoading, isError, isFetching, dataUpdatedAt } =
    useQuery<ProjectInsight>({
      queryKey: INSIGHT_KEY(projectId),
      // Hydrate instantly from the saved server snapshot (no forced run).
      queryFn: () => projectInsightApi.get(projectId),
      staleTime: 5 * 60_000,
      refetchInterval: (query) => {
        const latest = query.state.data as ProjectInsight | undefined;
        return latest?.stale ? 5_000 : false;
      },
    });

  // Explicit refresh only: a stale snapshot triggers the "updating…" indicator
  // and polls the snapshot GET until the background rebuild completes.
  const refresh = useMutation({
    mutationFn: () => projectInsightApi.refresh(projectId),
    onSuccess: (fresh) => {
      queryClient.setQueryData(INSIGHT_KEY(projectId), fresh);
    },
  });

  // Insights & opportunities — the same content as the Home page's
  // "Suggest Insights" pill, scoped to this project, rendered inline.
  const insightsQuery = useQuery({
    queryKey: [...INSIGHT_KEY(projectId), "suggested-insights"],
    queryFn: () => suggestInsights(3, Number(projectId)),
    staleTime: 5 * 60_000,
  });

  const analyzing = refresh.isPending || insightsQuery.isFetching;
  const updating = Boolean(data?.stale && isFetching);
  const handleRefresh = () => {
    refresh.mutate();
    insightsQuery.refetch();
  };

  useEffect(() => {
    if (isError && !loadErrorToasted) {
      push("Couldn't load Project Insight. Try refreshing.", "error");
      setLoadErrorToasted(true);
    }
  }, [isError, loadErrorToasted, push]);

  useEffect(() => {
    if (refresh.isPending) setRefreshErrorToasted(false);
    if (refresh.isError && !refreshErrorToasted) {
      push("Project Insight refresh failed. Try again later.", "error");
      setRefreshErrorToasted(true);
    }
  }, [refresh.isPending, refresh.isError, refreshErrorToasted, push]);

  const acknowledge = useMutation({
    mutationFn: (item: InsightWorkflowItem) =>
      projectInsightApi.acknowledge(projectId, item.id, {
        title: item.title,
        summary: item.evidenceSummary,
        category: item.type,
        severity: item.priority,
      }),
    onSuccess: (res) => {
      push(
        `Insight reviewed by ${res.acknowledgedByName || "you"}.`,
        "success",
      );
      queryClient.invalidateQueries({ queryKey: INSIGHT_KEY(projectId) });
      queryClient.invalidateQueries({ queryKey: REVIEWED_KEY(projectId) });
    },
    onError: () => push("Could not record review", "error"),
  });

  const reviewedQuery = useQuery({
    queryKey: REVIEWED_KEY(projectId),
    queryFn: () => projectInsightApi.reviewed(projectId),
  });

  const askQuestion = (
    question: string,
    source = "project_overview_question",
    cardContext?: AiCardContext,
  ) => {
    setAskModal({ open: true, question, source, cardContext });
  };

  const investigateCard = (card: ProjectInsightCard, source: string) =>
    askQuestion(card.question, source, cardContextFromCard(card));

  const handleCreateAction = (card: ProjectInsightCard) => {
    const projectName = data?.project.name ?? "";
    const insight: ActionableInsight = {
      insightId: card.id,
      insightType: card.insightType,
      title: card.title,
      summary: card.summary,
      severity: card.severity,
      projectId,
      projectName,
      recommendedAction: card.recommendedAction || null,
      sources: { tables: card.sourceTables ?? [], documents: [] },
      supportingSources: card.supportingSources ?? card.sourceTables ?? [],
      explanation: card.explanation as Record<string, unknown> | undefined,
    };
    setSelectedInsight(insight);
    setCreateActionOpen(true);
  };

  const openInAssistant = (question: string) => {
    setAskModal((m) => ({ ...m, open: false }));
    router.push(`/ai?projectId=${projectId}&q=${encodeURIComponent(question)}`);
  };

  const es = data?.executiveSummary;

  const questions = (data?.questionsToAsk ?? []).filter((q) =>
    q.question?.trim(),
  );
  const questionsNeedingData = (data?.questionsNeedingData ?? []).filter((q) =>
    (q.question || q.businessQuestion || q.title)?.trim(),
  );

  const reviewedItems: ReviewedInsight[] = reviewedQuery.data?.items ?? [];
  const reviewedIds = new Set(reviewedItems.map((i) => i.insightId));

  // Derive risks/trends/opportunities from the shared AI insight backend
  // (`/home/insights` → `_run_for_project`) instead of deterministic arrays.
  const allAiCards = useMemo(
    () =>
      insightsQuery.data?.projects?.flatMap((p) =>
        p.insights.map(toProjectInsightCard),
      ) ?? [],
    [insightsQuery.data],
  );
  const riskCards = useMemo(
    () =>
      allAiCards.filter(
        (c) =>
          c.insightType.startsWith("risk_") ||
          c.severity === "critical" ||
          c.severity === "urgent" ||
          c.severity === "warning",
      ),
    [allAiCards],
  );
  const trendCards = useMemo(
    () =>
      allAiCards.filter(
        (c) => c.insightType.startsWith("trend_") && !riskCards.includes(c),
      ),
    [allAiCards, riskCards],
  );
  const opportunityCards = useMemo(
    () =>
      allAiCards.filter(
        (c) =>
          (c.insightType.startsWith("opportunity_") ||
            c.severity === "opportunity") &&
          !riskCards.includes(c) &&
          !trendCards.includes(c),
      ),
    [allAiCards, riskCards, trendCards],
  );
  const allTrendCards = trendCards;

  const allInsightCards = allAiCards;
  const insightIds = useMemo(
    () => allInsightCards.map((c) => c.id).filter(Boolean),
    [allInsightCards],
  );
  const projectIdNum = Number(projectId);
  const {
    feedbackById,
    governanceById,
    saveFeedback,
    removeFeedback,
    respondToReview,
    saving: savingFeedback,
  } = useInsightFeedback(insightIds, Number.isNaN(projectIdNum) ? undefined : projectIdNum);

  const handleFeedbackSave = (
    card: ProjectInsightCard,
    payload: {
      sentiment: "agree" | "disagree";
      reason_codes: string[];
      comment: string;
    },
  ) => {
    const projectIdNum = Number(projectId);
    if (!card.id || Number.isNaN(projectIdNum)) return;
    void saveFeedback({
      insightId: card.id,
      projectId: projectIdNum,
      insightType: card.insightType,
      sentiment: payload.sentiment,
      reason_codes: payload.reason_codes,
      comment: payload.comment,
      cardSnapshot: card as unknown as Record<string, unknown>,
      explanationSnapshot: card.explanation,
    });
  };

  const handleFeedbackRemove = (card: ProjectInsightCard) => {
    const pid = Number(projectId);
    if (!card.id || Number.isNaN(pid)) return;
    void removeFeedback({ insightId: card.id, projectId: pid });
  };

  const handleFeedbackRespond = (card: ProjectInsightCard, response: string) => {
    if (!card.id) return;
    void respondToReview({ insightId: card.id, response });
  };

  const insightCount = (insightsQuery.data?.projects ?? []).reduce(
    (n, p) => n + p.insights.length,
    0,
  );
  const reviewCard = (card: ProjectInsightCard) =>
    acknowledge.mutate({
      id: card.id,
      title: card.title,
      type: card.insightType,
      priority: card.severity,
      evidenceSummary: card.summary,
    });

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-insights"
      breadcrumbLabel="Project Insight"
      actions={
        <div className="flex items-center gap-3">
          <span className="text-small text-ink-tertiary">
            {analyzing
              ? "Analyzing…"
              : updating
                ? "Updating…"
                : formatLastUpdated(
                    dataUpdatedAt ? new Date(dataUpdatedAt) : null,
                  )}
          </span>
          <Button
            variant="secondary"
            onClick={handleRefresh}
            disabled={analyzing}
          >
            <IconRefresh
              size={14}
              className={analyzing ? "animate-spin" : ""}
            />
            Refresh
          </Button>
        </div>
      }
    >
      <div className="mx-auto w-full max-w-content space-y-4 py-4">
        {isLoading ? (
          <LoadingState />
        ) : isError ? (
          <EmptyState
            title="Couldn't load Project Insight"
            body="Something went wrong building this project's insight. Try refreshing."
          />
        ) : !data ? null : (
          <>
            {/* 0. Ask + AI suggestions — same experience as Business Insight,
                scoped to this project. The ask box hands off to the shared
                conversational-analytics assistant; the pills generate query/
                dashboard/insight suggestions for this project only. */}
            <div className="space-y-6 py-2">
              <HomeAiSuggestions projectId={Number(projectId)} />
            </div>

            {/* 1. Executive Project Summary */}
            <section className="rounded-lg border border-line-tertiary bg-bg-primary p-5">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <IconSparkles size={18} className="text-brand-500" />
                  <h2 className="text-h2 text-ink-primary">
                    Executive Project Summary
                  </h2>
                </div>
                <Badge tone="ai" size="md">
                  AI Generated
                </Badge>
              </div>
              <p className="max-w-4xl text-[13px] leading-relaxed text-ink-secondary">
                {es?.summary || "No summary available for this project yet."}
              </p>
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <SummaryCard
                  title="Critical"
                  tone="danger"
                  icon={<IconAlertCircle size={15} />}
                  items={es?.critical ?? []}
                />
                <SummaryCard
                  title="Warnings"
                  tone="warning"
                  icon={<IconAlertTriangle size={15} />}
                  items={es?.warnings ?? []}
                />
                <SummaryCard
                  title="Opportunities"
                  tone="success"
                  icon={<IconArrowUpRight size={15} />}
                  items={es?.opportunities ?? []}
                />
                <SummaryCard
                  title="Recommendations"
                  tone="brand"
                  icon={<IconBulb size={15} />}
                  items={es?.recommendations ?? []}
                />
              </div>
            </section>

            {/* Risks / Trends / Opportunities cards */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <InsightCardColumn
                title="Risks"
                icon={
                  <IconAlertTriangle size={16} className="text-danger" />
                }
                cards={riskCards}
                emptyText="No risks detected from this project's data yet."
                reviewedIds={reviewedIds}
                projectId={projectId}
                projectName={data?.project.name ?? ""}
                feedbackById={feedbackById}
                savingFeedback={savingFeedback}
                onInvestigate={(c) =>
                  investigateCard(c, "project_insight_risk")
                }
                onReview={reviewCard}
                onFeedbackSave={handleFeedbackSave}
                onFeedbackRemove={handleFeedbackRemove}
                onFeedbackRespond={handleFeedbackRespond}
                governanceById={governanceById}
                onCreateAction={handleCreateAction}
                reviewPending={acknowledge.isPending}
                reviewPendingId={acknowledge.variables?.id}
              />
              <InsightCardColumn
                title="Trends"
                icon={
                  <IconTrendingUp size={16} className="text-brand-500" />
                }
                cards={allTrendCards}
                emptyText="No trends detected from this project's data yet."
                reviewedIds={reviewedIds}
                projectId={projectId}
                projectName={data?.project.name ?? ""}
                feedbackById={feedbackById}
                savingFeedback={savingFeedback}
                onInvestigate={(c) =>
                  investigateCard(c, "project_insight_trend")
                }
                onReview={reviewCard}
                onFeedbackSave={handleFeedbackSave}
                onFeedbackRemove={handleFeedbackRemove}
                onFeedbackRespond={handleFeedbackRespond}
                governanceById={governanceById}
                onCreateAction={handleCreateAction}
                reviewPending={acknowledge.isPending}
                reviewPendingId={acknowledge.variables?.id}
              />
              <InsightCardColumn
                title="Opportunities"
                icon={<IconBulb size={16} className="text-success" />}
                cards={opportunityCards}
                emptyText="No opportunities detected from this project's data yet."
                reviewedIds={reviewedIds}
                projectId={projectId}
                projectName={data?.project.name ?? ""}
                feedbackById={feedbackById}
                savingFeedback={savingFeedback}
                onInvestigate={(c) =>
                  investigateCard(c, "project_insight_opportunity")
                }
                onReview={reviewCard}
                onFeedbackSave={handleFeedbackSave}
                onFeedbackRemove={handleFeedbackRemove}
                onFeedbackRespond={handleFeedbackRespond}
                governanceById={governanceById}
                onCreateAction={handleCreateAction}
                reviewPending={acknowledge.isPending}
                reviewPendingId={acknowledge.variables?.id}
              />
            </div>

            {/* Insights & Opportunities (expanded by default) */}
            <Panel
              title="Insights & Opportunities"
              icon={<IconSparkles size={16} className="text-brand-500" />}
              collapsible
              defaultOpen={true}
              count={insightCount}
            >
              {insightsQuery.isFetching && !insightsQuery.data ? (
                <div className="flex items-center gap-2 py-8 text-small text-ink-tertiary">
                  <IconLoader2 size={16} className="animate-spin" />
                  Analyzing this project…
                </div>
              ) : (
                <InsightsPanel
                  projects={insightsQuery.data?.projects ?? []}
                  showProjectHeader={false}
                  onPin={handlePinInsight}
                  pinnedByFingerprint={pinnedByFingerprint}
                />
              )}
            </Panel>

            {/* AI-Generated Questions to Ask (collapsed by default) */}
            <Panel
              title="AI-Generated Questions to Ask"
              icon={<IconHelpCircle size={16} className="text-brand-500" />}
              collapsible
              defaultOpen={false}
              count={questions.length}
            >
              {questions.length === 0 ? (
                <PanelEmpty text="No suggested questions yet." />
              ) : (
                <ul className="divide-y divide-line-tertiary">
                  {questions.map((q) => (
                    <li key={q.id}>
                      <button
                        type="button"
                        onClick={() => askQuestion(q.question)}
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
              )}
              {questionsNeedingData.length > 0 && (
                <div className="mt-3 border-t border-line-tertiary pt-3">
                  <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-ink-tertiary">
                    <IconAlertCircle size={14} className="text-warning" />
                    Needs additional data
                  </div>
                  <ul className="space-y-2">
                    {questionsNeedingData.map((q, i) => {
                      const text =
                        q.question || q.businessQuestion || q.title || "";
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
            </Panel>


          </>
        )}
      </div>
      <AIQuestionResultModal
        open={askModal.open}
        projectId={projectId}
        question={askModal.question}
        source={askModal.source}
        cardContext={askModal.cardContext}
        onClose={() => setAskModal((m) => ({ ...m, open: false }))}
        onOpenAssistant={openInAssistant}
        notify={push}
      />

      <CreateActionFromInsightDialog
        open={createActionOpen}
        onClose={() => setCreateActionOpen(false)}
        insight={selectedInsight}
      />

      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}

function SummaryCard({
  title,
  tone,
  icon,
  items,
}: {
  title: string;
  tone: keyof typeof SUMMARY_TONES;
  icon: ReactNode;
  items: string[];
}) {
  const t = SUMMARY_TONES[tone];

  return (
    <div className={cn("rounded-lg border p-3.5", t.box)}>
      <div
        className={cn(
          "mb-1.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide",
          t.label,
        )}
      >
        {icon}
        {title}
      </div>
      {items.length === 0 ? (
        <p className="text-small text-ink-tertiary">None</p>
      ) : (
        <ul className="space-y-1">
          {items.map((it, i) => (
            <li
              key={i}
              className="text-[13px] leading-snug text-ink-secondary"
            >
              {it}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function InsightCardColumn({
  title,
  icon,
  cards,
  emptyText,
  reviewedIds,
  projectId,
  projectName,
  feedbackById,
  governanceById,
  savingFeedback,
  onInvestigate,
  onReview,
  onFeedbackSave,
  onFeedbackRemove,
  onFeedbackRespond,
  onCreateAction,
  reviewPending,
  reviewPendingId,
}: {
  title: string;
  icon: ReactNode;
  cards: ProjectInsightCard[];
  emptyText: string;
  reviewedIds: Set<string>;
  projectId: string;
  projectName: string;
  feedbackById: Record<string, InsightFeedbackRecord>;
  governanceById?: Record<string, GovernanceItem>;
  savingFeedback: boolean;
  onInvestigate: (card: ProjectInsightCard) => void;
  onReview: (card: ProjectInsightCard) => void;
  onFeedbackSave?: (card: ProjectInsightCard, payload: {
    sentiment: "agree" | "disagree";
    reason_codes: string[];
    comment: string;
  }) => void;
  onFeedbackRemove?: (card: ProjectInsightCard) => void;
  onFeedbackRespond?: (card: ProjectInsightCard, response: string) => void;
  onCreateAction?: (card: ProjectInsightCard) => void;
  reviewPending: boolean;
  reviewPendingId?: string;
}) {
  return (
    <Panel title={title} icon={icon}>
      {cards.length === 0 ? (
        <PanelEmpty text={emptyText} />
      ) : (
        <div className="space-y-3">
          {cards.map((card) => (
            <InsightCardItem
              key={card.id}
              card={card}
              projectId={projectId}
              projectName={projectName}
              reviewed={reviewedIds.has(card.id)}
              feedback={feedbackById[card.id]}
              savingFeedback={savingFeedback}
              onInvestigate={() => onInvestigate(card)}
              onReview={() => onReview(card)}
              onFeedbackSave={onFeedbackSave ? (payload) => onFeedbackSave(card, payload) : undefined}
              onFeedbackRemove={onFeedbackRemove ? () => onFeedbackRemove(card) : undefined}
              onFeedbackRespond={onFeedbackRespond ? (response) => onFeedbackRespond(card, response) : undefined}
              governance={governanceById?.[card.id]}
              onCreateAction={onCreateAction ? () => onCreateAction(card) : undefined}
              reviewPending={reviewPending && reviewPendingId === card.id}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

function InsightCardItem({
  card,
  projectId,
  projectName,
  reviewed,
  feedback,
  savingFeedback,
  onInvestigate,
  onReview,
  onFeedbackSave,
  onFeedbackRemove,
  onFeedbackRespond,
  onCreateAction,
  governance,
  reviewPending,
}: {
  card: ProjectInsightCard;
  projectId: string;
  projectName: string;
  reviewed: boolean;
  feedback?: InsightFeedbackRecord | null;
  savingFeedback?: boolean;
  onInvestigate: () => void;
  onReview: () => void;
  onFeedbackSave?: (payload: {
    sentiment: "agree" | "disagree";
    reason_codes: string[];
    comment: string;
  }) => void;
  onFeedbackRemove?: () => void;
  onFeedbackRespond?: (response: string) => void | Promise<void>;
  onCreateAction?: () => void;
  governance?: GovernanceItem | null;
  reviewPending: boolean;
}) {
  const [explainOpen, setExplainOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [statusDialogOpen, setStatusDialogOpen] = useState(false);
  const [chartDialogOpen, setChartDialogOpen] = useState(false);
  const [feedbackInitial, setFeedbackInitial] = useState<InsightSentiment>("agree");
  const hasFeedback = feedback != null && feedback.status === "active";
  const { data: identity } = useCurrentUser();
  const canCreateAction =
    onCreateAction &&
    canManageProjectActions(identity?.user?.rawRole, identity?.user?.isSuperAdmin);
  const sev = CARD_SEVERITY[card.severity] ?? CARD_SEVERITY.informational;

  const tables = card.sourceTables ?? card.supportingSources.filter(
    (s) => !/\.(pdf|docx?|txt|csv)$/i.test(s),
  );
  const documents = card.supportingSources.filter((s) =>
    /\.(pdf|docx?|txt|csv)$/i.test(s),
  );

  const insightCardData: InsightCardData = {
    id: card.id,
    insightId: card.id,
    projectId,
    projectName,
    projectColor: "",
    insightType: card.insightType,
    severity: card.severity as InsightCardData["severity"],
    title: card.title,
    summary: card.summary,
    chart: card.chart ?? null,
    callout: null,
    sources: { tables, documents },
    executedAt: card.executedAt ?? "",
    sql: card.sql,
    chartType: card.chartType,
    labelColumn: card.labelColumn,
    valueColumn: card.valueColumn,
    valueColumn2: card.valueColumn2,
    explanation: card.explanation as InsightExplanation | undefined,
    analyticalMethod: card.analyticalMethod,
    evidenceFingerprint: card.evidenceFingerprint,
    confidenceScore: card.confidenceScore,
    confidenceEvaluation: card.confidenceEvaluation as InsightCardData["confidenceEvaluation"],
    visualizationDecision: card.visualizationDecision as InsightCardData["visualizationDecision"],
    chartCandidates: card.chartCandidates as InsightCardData["chartCandidates"],
  };

  return (
    <article className="rounded-md border border-line-tertiary bg-bg-primary p-3">
      <header className="flex items-start justify-between gap-2">
        <h4 className="min-w-0 text-[13px] font-semibold text-ink-primary">
          {card.title}
        </h4>
        <div className="flex shrink-0 items-center gap-1.5">
          <InsightGovernanceBadge status={governance?.governance_status} />
          <span
            className={cn(
              "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
              sev.chip,
            )}
          >
            {sev.label}
          </span>
        </div>
      </header>
      <p className="mt-1 text-[13px] leading-snug text-ink-secondary">
        <span className="text-ink-tertiary">Summary: </span>
        {renderBold(card.summary)}
      </p>
      {card.recommendedAction && (
        <div className="mt-2 flex items-start gap-1.5 rounded-md bg-bg-secondary/60 p-2 text-small text-ink-secondary">
          <IconBulb size={14} className="mt-0.5 shrink-0 text-brand-500" />
          <span>{renderBold(card.recommendedAction)}</span>
        </div>
      )}
      {card.supportingSources.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-tertiary">
          {card.supportingSources.slice(0, 3).map((s) => (
            <span key={s} className="inline-flex items-center gap-1">
              {/\.(pdf|docx?|txt|csv)$/i.test(s) ? (
                <IconFileText size={12} />
              ) : (
                <IconTable size={12} />
              )}
              {s}
            </span>
          ))}
        </div>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-line-tertiary pt-2.5">
        <Button variant="secondary" size="sm" onClick={onInvestigate}>
          <IconSearch size={13} />
          Investigate
        </Button>
        {reviewed ? (
          <Badge tone="success" size="sm">
            <IconCheck size={12} />
            Reviewed
          </Badge>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            onClick={onReview}
            disabled={reviewPending}
          >
            {reviewPending ? "Saving…" : "Mark reviewed"}
          </Button>
        )}
        <button
          type="button"
          onClick={() => setExplainOpen(true)}
          className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-[11px] font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
        >
          <IconInfoCircle size={13} />
          Explain
        </button>

        <button
          type="button"
          onClick={() => setChartDialogOpen(true)}
          className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-[11px] font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
        >
          <IconChartBar size={13} />
          Chart suggestion
        </button>

        <RAnalyticsBadge envelope={card.analyticalMethod} />

        {canCreateAction && (
          <button
            type="button"
            onClick={onCreateAction}
            className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-[11px] font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary"
          >
            <IconClipboardList size={13} />
            Action
          </button>
        )}
        {onFeedbackSave && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setFeedbackInitial("agree");
                setFeedbackOpen(true);
              }}
              aria-label={
                hasFeedback && feedback?.sentiment === "agree"
                  ? "Edit agree feedback"
                  : "Agree"
              }
              title={
                hasFeedback && feedback?.sentiment === "agree"
                  ? "Edit agree feedback"
                  : "Agree"
              }
              className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                hasFeedback && feedback?.sentiment === "agree"
                  ? "border-success bg-success/10 text-success hover:bg-success/20"
                  : "border-line-tertiary text-ink-secondary hover:border-line-secondary hover:bg-bg-tertiary"
              }`}
            >
              <IconThumbUp size={13} />
              Agree
            </button>
            <button
              type="button"
              onClick={() => {
                setFeedbackInitial("disagree");
                setFeedbackOpen(true);
              }}
              aria-label={
                hasFeedback && feedback?.sentiment === "disagree"
                  ? "Edit disagree feedback"
                  : "Disagree"
              }
              title={
                hasFeedback && feedback?.sentiment === "disagree"
                  ? "Edit disagree feedback"
                  : "Disagree"
              }
              className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                hasFeedback && feedback?.sentiment === "disagree"
                  ? "border-danger bg-danger/10 text-danger hover:bg-danger/20"
                  : "border-line-tertiary text-ink-secondary hover:border-line-secondary hover:bg-bg-tertiary"
              }`}
            >
              <IconThumbDown size={13} />
              Disagree
            </button>
            <InsightFeedbackStatusBadge
              feedback={feedback}
              onClick={() => setStatusDialogOpen(true)}
            />
          </div>
        )}
      </div>

      <InsightExplanationPanel
        card={insightCardData}
        open={explainOpen}
        onClose={() => setExplainOpen(false)}
      />
      {onFeedbackSave && (
        <InsightFeedbackDialog
          card={insightCardData}
          open={feedbackOpen}
          onClose={() => setFeedbackOpen(false)}
          feedback={feedback || null}
          initialSentiment={feedbackInitial}
          onSave={onFeedbackSave}
          onRemove={async () => {
            await onFeedbackRemove?.();
            setFeedbackOpen(false);
          }}
          saving={savingFeedback}
        />
      )}

      {feedback && (
        <InsightFeedbackStatusDialog
          open={statusDialogOpen}
          onClose={() => setStatusDialogOpen(false)}
          feedback={feedback}
          title={card.title}
          onRespond={onFeedbackRespond ? (response) => void onFeedbackRespond(response) : undefined}
          onEdit={() => {
            setStatusDialogOpen(false);
            setFeedbackOpen(true);
          }}
          onWithdraw={async () => {
            await onFeedbackRemove?.();
            setStatusDialogOpen(false);
          }}
          responding={false}
          withdrawing={savingFeedback}
        />
      )}

      <ChartSuggestionDialog
        card={insightCardData}
        projectId={Number(projectId)}
        open={chartDialogOpen}
        onClose={() => setChartDialogOpen(false)}
      />
    </article>
  );
}

function LoadingState() {
  return (
    <div className="space-y-4">
      <div className="h-40 animate-pulse rounded-lg bg-bg-secondary" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="h-48 animate-pulse rounded-lg bg-bg-secondary" />
        <div className="h-48 animate-pulse rounded-lg bg-bg-secondary" />
      </div>
    </div>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary py-16 text-center">
      <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-500">
        <IconSparkles size={22} />
      </div>
      <div className="text-h2 text-ink-primary">{title}</div>
      <p className="mx-auto mt-1 max-w-md text-small text-ink-tertiary">{body}</p>
    </div>
  );
}
