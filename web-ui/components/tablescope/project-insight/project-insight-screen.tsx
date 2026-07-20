"use client";

import { type ReactNode, useMemo, useState } from "react";
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
  IconLayoutDashboard,
  IconCode,
  IconTargetArrow,
  IconCheck,
  IconChevronRight,
  IconSearch,
  IconTable,
  IconFileText,
  IconLoader2,
  IconInfoCircle,
  IconThumbUp,
  IconThumbDown,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { cn } from "@/lib/cn";
import {
  InsightPanel as Panel,
  PanelEmpty,
} from "@/components/tablescope/insight-panel";
import { AIQuestionResultModal } from "@/components/ai/AIQuestionResultModal";
import { GenerateQueryPreviewModal } from "@/components/ai/GenerateQueryPreviewModal";
import type { AiCardContext } from "@/lib/api/ai-actions";
import { GenerateDashboardModal } from "@/components/tablescope/project-insight/generate-dashboard-modal";
import { renderBold } from "@/components/tablescope/home/intelligence-card";
import { InsightsPanel, HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import {
  InsightExplanationPanel,
} from "@/components/tablescope/home/insight-explanation-panel";
import {
  InsightFeedbackDialog,
} from "@/components/tablescope/home/insight-feedback-dialog";
import {
  suggestInsights,
  type InsightCard as InsightCardData,
  type InsightExplanation,
} from "@/lib/api/home-intelligence";
import type { InsightFeedbackRecord } from "@/lib/api/insight-feedback";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";
import { formatLastUpdated } from "@/lib/format-datetime";
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

export function ProjectInsightScreen({ projectId }: { projectId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { toasts, push, dismiss } = useToasts();
  const [askModal, setAskModal] = useState<{
    open: boolean;
    question: string;
    source: string;
    cardContext?: AiCardContext;
  }>({ open: false, question: "", source: "" });
  const [queryPreview, setQueryPreview] = useState<{
    open: boolean;
    question: string;
    title: string;
    description: string;
    cardContext?: AiCardContext;
  }>({ open: false, question: "", title: "", description: "" });
  const [dashboardGen, setDashboardGen] = useState<{ open: boolean }>({
    open: false,
  });
  const [customQuestion, setCustomQuestion] = useState("");

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

  const submitCustomQuestion = () => {
    const q = customQuestion.trim();
    if (!q) return;
    askQuestion(q, "project_custom_question");
    setCustomQuestion("");
  };

  const openInAssistant = (question: string) => {
    setAskModal((m) => ({ ...m, open: false }));
    router.push(`/projects/${projectId}/ai?q=${encodeURIComponent(question)}`);
  };

  const es = data?.executiveSummary;

  const questions = (data?.questionsToAsk ?? []).filter((q) =>
    q.question?.trim(),
  );
  const questionsNeedingData = (data?.questionsNeedingData ?? []).filter((q) =>
    (q.question || q.businessQuestion || q.title)?.trim(),
  );
  const dashboards = (data?.recommendedDashboards ?? []).filter((d) =>
    d.title?.trim(),
  );
  const queries = (data?.recommendedQueries ?? []).filter((q) =>
    q.title?.trim(),
  );
  const kpis = (data?.recommendedKpis ?? []).filter((k) => k.name?.trim());
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
  const {
    feedbackById,
    saveFeedback,
    removeFeedback,
    saving: savingFeedback,
  } = useInsightFeedback(insightIds);

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
    const projectIdNum = Number(projectId);
    if (!card.id || Number.isNaN(projectIdNum)) return;
    void removeFeedback({ insightId: card.id, projectId: projectIdNum });
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
            {data.aiAvailable === false && (
              <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning-bg px-3 py-2 text-[13px] text-warning">
                <IconAlertCircle size={15} />
                AI insight is temporarily unavailable — showing activity only.
                Try Refresh in a moment.
              </div>
            )}

            {data.stale && (
              <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-[13px] text-ink-secondary">
                <IconLoader2 size={15} className="animate-spin" />
                Updating project insight to reflect the latest data…
              </div>
            )}

            {data.graphMode && data.graphMode !== "full" && (
              <div
                className={cn(
                  "flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px]",
                  data.graphMode === "blocked"
                    ? "border-danger/30 bg-danger-bg text-danger"
                    : "border-warning/30 bg-warning-bg text-warning",
                )}
              >
                {data.graphMode === "blocked" ? (
                  <IconAlertTriangle size={15} className="mt-0.5 shrink-0" />
                ) : (
                  <IconAlertCircle size={15} className="mt-0.5 shrink-0" />
                )}
                <div className="min-w-0">
                  <p>{data.graphDisclosure}</p>
                  {data.graphBlockingReasons.length > 0 && (
                    <ul className="mt-1 list-disc pl-4 text-[12px]">
                      {data.graphBlockingReasons.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}

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
                reviewPending={acknowledge.isPending}
                reviewPendingId={acknowledge.variables?.id}
              />
            </div>

            {/* Insights & Opportunities (collapsed by default) */}
            <Panel
              title="Insights & Opportunities"
              icon={<IconSparkles size={16} className="text-brand-500" />}
              collapsible
              defaultOpen={false}
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

            {/* Ask box — always visible between Questions and Recommendations */}
            <div className="flex items-center gap-2 rounded-lg border border-line-tertiary bg-bg-primary px-4 py-3">
              <input
                type="text"
                value={customQuestion}
                onChange={(e) => setCustomQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    submitCustomQuestion();
                  }
                }}
                placeholder="Ask a question about this project..."
                aria-label="Ask a question about this project"
                className="min-w-0 flex-1 rounded-md border border-line-tertiary bg-bg-primary px-2.5 py-1.5 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
              />
              <Button
                variant="primary"
                size="sm"
                disabled={!customQuestion.trim()}
                onClick={submitCustomQuestion}
              >
                <IconSparkles size={14} />
                Ask
              </Button>
            </div>

            {/* Recommendations (collapsed by default) — Dashboards | Queries | KPIs */}
            <Panel
              title="Recommendations"
              icon={<IconBulb size={16} className="text-brand-500" />}
              collapsible
              defaultOpen={false}
            >
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <Panel
                  title="Recommended Dashboards"
                  icon={
                    <IconLayoutDashboard
                      size={16}
                      className="text-brand-500"
                    />
                  }
                >
                  {dashboards.length === 0 ? (
                    <PanelEmpty text="No dashboard suggestions." />
                ) : (
                  <div className="space-y-2.5">
                    {dashboards.map((d) => (
                      <SuggestionRow
                        key={d.id}
                        title={d.title ?? ""}
                        subtitle={d.description || d.reason}
                        status={d.status}
                        action={d.action}
                        onGenerate={() => setDashboardGen({ open: true })}
                      />
                    ))}
                  </div>
                )}
              </Panel>

              <Panel
                title="Recommended Queries"
                icon={<IconCode size={16} className="text-brand-500" />}
              >
                {queries.length === 0 ? (
                  <PanelEmpty text="No query suggestions." />
                ) : (
                  <div className="space-y-2.5">
                    {queries.map((q) => (
                      <SuggestionRow
                        key={q.id}
                        title={q.title ?? ""}
                        subtitle={q.businessQuestion || q.reason}
                        status={q.status}
                        action={q.action}
                        onGenerate={() =>
                          setQueryPreview({
                            open: true,
                            question:
                              q.businessQuestion || q.title || "",
                            title: q.title ?? "",
                            description: q.businessQuestion || q.reason || "",
                            cardContext: {
                              source_tables: q.recommendedTables,
                              source_columns: q.sourceColumns,
                              metric: q.metric,
                            },
                          })
                        }
                      />
                    ))}
                  </div>
                )}
              </Panel>

              <Panel
                title="Recommended KPIs"
                icon={<IconTargetArrow size={16} className="text-brand-500" />}
              >
                {kpis.length === 0 ? (
                  <PanelEmpty text="No KPI suggestions." />
                ) : (
                  <div className="space-y-2.5">
                    {kpis.map((k) => (
                      <div
                        key={k.id}
                        className="rounded-md border border-line-tertiary px-3 py-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[13px] font-medium text-ink-primary">
                            {k.name}
                          </span>
                          <KpiStatusBadge status={k.status} />
                        </div>
                        {(k.currentValue !== null &&
                          k.currentValue !== undefined) && (
                          <div className="mt-0.5 text-[15px] font-semibold text-ink-primary">
                            {k.currentValue}
                            {k.unit ? ` ${k.unit}` : ""}
                          </div>
                        )}
                        {k.description && (
                          <div className="mt-0.5 text-small text-ink-tertiary">
                            {k.description}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Panel>
              </div>
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
      <GenerateQueryPreviewModal
        open={queryPreview.open}
        projectId={projectId}
        question={queryPreview.question}
        title={queryPreview.title}
        description={queryPreview.description}
        cardContext={queryPreview.cardContext}
        onClose={() => setQueryPreview((m) => ({ ...m, open: false }))}
        onSaved={() => {
          queryClient.invalidateQueries({
            queryKey: ["project", projectId, "queries"],
          });
        }}
        notify={push}
      />
      {dashboardGen.open && (
        <GenerateDashboardModal
          open={dashboardGen.open}
          projectId={projectId}
          onClose={() => setDashboardGen({ open: false })}
          onSaved={() => {
            queryClient.invalidateQueries({
              queryKey: ["project", projectId, "dashboards"],
            });
          }}
          notify={push}
        />
      )}
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
  savingFeedback,
  onInvestigate,
  onReview,
  onFeedbackSave,
  onFeedbackRemove,
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
  savingFeedback: boolean;
  onInvestigate: (card: ProjectInsightCard) => void;
  onReview: (card: ProjectInsightCard) => void;
  onFeedbackSave?: (card: ProjectInsightCard, payload: {
    sentiment: "agree" | "disagree";
    reason_codes: string[];
    comment: string;
  }) => void;
  onFeedbackRemove?: (card: ProjectInsightCard) => void;
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
  reviewPending: boolean;
}) {
  const [explainOpen, setExplainOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const hasFeedback = feedback != null && feedback.status === "active";
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
    chart: null,
    callout: null,
    sources: { tables, documents },
    executedAt: card.executedAt ?? "",
    sql: card.sql,
    chartType: card.chartType,
    labelColumn: card.labelColumn,
    valueColumn: card.valueColumn,
    valueColumn2: card.valueColumn2,
    explanation: card.explanation as InsightExplanation | undefined,
  };

  return (
    <article className="rounded-md border border-line-tertiary bg-bg-primary p-3">
      <header className="flex items-start justify-between gap-2">
        <h4 className="min-w-0 text-[13px] font-semibold text-ink-primary">
          {card.title}
        </h4>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
            sev.chip,
          )}
        >
          {sev.label}
        </span>
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
        {onFeedbackSave && (
          <button
            type="button"
            onClick={() => setFeedbackOpen(true)}
            aria-label={hasFeedback ? "Edit feedback" : "Give feedback"}
            title={hasFeedback ? "Edit feedback" : "Give feedback"}
            className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors ${
              hasFeedback
                ? "border-brand-500 bg-brand-50 text-brand-700 hover:bg-brand-100"
                : "border-line-tertiary text-ink-secondary hover:border-line-secondary hover:bg-bg-tertiary"
            }`}
          >
            {feedback?.sentiment === "disagree" ? (
              <IconThumbDown size={13} />
            ) : (
              <IconThumbUp size={13} />
            )}
            {hasFeedback ? "Feedback saved" : "Agree"}
          </button>
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
          onSave={onFeedbackSave}
          onRemove={async () => {
            await onFeedbackRemove?.();
            setFeedbackOpen(false);
          }}
          saving={savingFeedback}
        />
      )}
    </article>
  );
}

function statusLabel(status?: string): string {
  switch (status) {
    case "saved":
    case "generated":
      return "Open";
    case "measured":
      return "Measured";
    case "partially_measured":
      return "Partial";
    case "missing_data":
      return "Missing Data";
    default:
      return "Suggested";
  }
}

function SuggestionRow({
  title,
  subtitle,
  status,
  action,
  onGenerate,
}: {
  title: string;
  subtitle?: string;
  status?: string;
  action?: string;
  onGenerate?: () => void;
}) {
  const actionLabel =
    action === "open"
      ? "Open"
      : action === "run"
        ? "Run"
        : action === "save"
          ? "Save"
          : "Generate";
  return (
    <div className="rounded-md border border-line-tertiary px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[13px] font-medium text-ink-primary">{title}</span>
        <Badge
          tone={status === "saved" || status === "measured" ? "success" : "brand"}
          size="sm"
        >
          {statusLabel(status)}
        </Badge>
      </div>
      {subtitle && (
        <div className="mt-0.5 text-small text-ink-tertiary">{subtitle}</div>
      )}
      <div className="mt-1.5">
        {onGenerate ? (
          <Button variant="secondary" size="sm" onClick={onGenerate}>
            <IconSparkles size={13} />
            {actionLabel}
          </Button>
        ) : (
          <Badge tone="outline" size="sm">
            {actionLabel}
          </Badge>
        )}
      </div>
    </div>
  );
}

function KpiStatusBadge({ status }: { status?: string }) {
  const tone =
    status === "measured"
      ? "success"
      : status === "missing_data"
        ? "warning"
        : "brand";
  return (
    <Badge tone={tone} size="sm">
      {statusLabel(status)}
    </Badge>
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
