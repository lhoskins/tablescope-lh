"use client";

import { type ReactNode, useState } from "react";
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
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { cn } from "@/lib/cn";
import { AIQuestionResultModal } from "@/components/ai/AIQuestionResultModal";
import { GenerateQueryPreviewModal } from "@/components/ai/GenerateQueryPreviewModal";
import { GenerateDashboardModal } from "@/components/tablescope/project-insight/generate-dashboard-modal";
import {
  projectInsightApi,
  type ProjectInsight,
  type InsightWorkflowItem,
  type ReviewedInsight,
} from "@/lib/api/project-insight";

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
  }>({ open: false, question: "", source: "" });
  const [queryPreview, setQueryPreview] = useState<{
    open: boolean;
    question: string;
    title: string;
    description: string;
  }>({ open: false, question: "", title: "", description: "" });
  const [dashboardGen, setDashboardGen] = useState<{ open: boolean }>({
    open: false,
  });
  const [customQuestion, setCustomQuestion] = useState("");

  const { data, isLoading, isError, refetch, isFetching } =
    useQuery<ProjectInsight>({
      queryKey: INSIGHT_KEY(projectId),
      queryFn: () => projectInsightApi.get(projectId),
    });

  const [workflowTab, setWorkflowTab] = useState<"open" | "reviewed">("open");

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

  const reopen = useMutation({
    mutationFn: (insightId: string) =>
      projectInsightApi.reopen(projectId, insightId),
    onSuccess: () => {
      push("Insight reopened.", "success");
      queryClient.invalidateQueries({ queryKey: INSIGHT_KEY(projectId) });
      queryClient.invalidateQueries({ queryKey: REVIEWED_KEY(projectId) });
    },
    onError: () => push("Could not reopen insight", "error"),
  });

  const askQuestion = (question: string, source = "project_overview_question") => {
    setAskModal({ open: true, question, source });
  };

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
  const trends = (data?.trendDetection ?? []).filter((t) =>
    (t.label || t.title || t.description)?.trim(),
  );
  const dashboards = (data?.recommendedDashboards ?? []).filter((d) =>
    d.title?.trim(),
  );
  const queries = (data?.recommendedQueries ?? []).filter((q) =>
    q.title?.trim(),
  );
  const kpis = (data?.recommendedKpis ?? []).filter((k) => k.name?.trim());
  const workflow = (data?.insightValidationWorkflow ?? []).filter((i) =>
    i.title?.trim(),
  );
  const openWorkflow = workflow.filter((i) => i.status !== "reviewed");
  const reviewedItems: ReviewedInsight[] = reviewedQuery.data?.items ?? [];

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-insight"
      breadcrumbLabel="Project Insight"
      actions={
        <Button
          variant="secondary"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <IconRefresh size={14} className={isFetching ? "animate-spin" : ""} />
          Refresh
        </Button>
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
              <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
                <SummaryColumn
                  title="Critical"
                  tone="danger"
                  icon={<IconAlertCircle size={15} />}
                  items={es?.critical ?? []}
                />
                <SummaryColumn
                  title="Warnings"
                  tone="warning"
                  icon={<IconAlertTriangle size={15} />}
                  items={es?.warnings ?? []}
                />
                <SummaryColumn
                  title="Opportunities"
                  tone="success"
                  icon={<IconArrowUpRight size={15} />}
                  items={es?.opportunities ?? []}
                />
                <SummaryColumn
                  title="Recommendations"
                  tone="brand"
                  icon={<IconBulb size={15} />}
                  items={es?.recommendations ?? []}
                />
              </div>
            </section>

            {/* 2 + 3. Questions to Ask | Trend Detection */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Panel
                title="AI-Generated Questions to Ask"
                icon={<IconHelpCircle size={16} className="text-brand-500" />}
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
                <div className="mt-3 flex items-center gap-2 border-t border-line-tertiary pt-3">
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
              </Panel>

              <Panel
                title="Trend Detection"
                icon={<IconTrendingUp size={16} className="text-brand-500" />}
              >
                {trends.length === 0 ? (
                  <PanelEmpty text="No trends detected yet." />
                ) : (
                  <div className="space-y-3">
                    {trends.map((t) => (
                      <div key={t.id} className="text-[13px]">
                        <div className="flex items-baseline gap-2">
                          {t.label && (
                            <span className="font-medium text-ink-primary">
                              {t.label}
                            </span>
                          )}
                          <span className="text-ink-secondary">
                            {t.title || t.description}
                          </span>
                        </div>
                        {t.possibleCause && (
                          <div className="mt-0.5 text-small text-ink-tertiary">
                            Possible cause: {t.possibleCause}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Panel>
            </div>

            {/* 4 + 5 + 6. Recommended Dashboards | Queries | KPIs */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <Panel
                title="Recommended Dashboards"
                icon={
                  <IconLayoutDashboard size={16} className="text-brand-500" />
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

            {/* 7 + 8. What Changed | Insight Validation Workflow */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
              <div className="lg:col-span-2">
                <Panel
                  title="What Changed Since Last Visit"
                  icon={<IconRefresh size={16} className="text-brand-500" />}
                >
                  <dl className="space-y-2">
                    <ChangeRow
                      label="New files added"
                      value={data.whatChangedSinceLastVisit.newFilesAdded}
                    />
                    <ChangeRow
                      label="Changed data sources"
                      value={data.whatChangedSinceLastVisit.changedDataSources}
                    />
                    <ChangeRow
                      label="New risks identified"
                      value={data.whatChangedSinceLastVisit.newRisksIdentified}
                    />
                    <ChangeRow
                      label="New queries"
                      value={data.whatChangedSinceLastVisit.newQueries}
                    />
                    <ChangeRow
                      label="New dashboards"
                      value={data.whatChangedSinceLastVisit.newDashboards}
                    />
                    <ChangeRow
                      label="Updated knowledge graph"
                      value={data.whatChangedSinceLastVisit.updatedKnowledgeGraph}
                    />
                  </dl>
                </Panel>
              </div>

              <div className="lg:col-span-3">
                <Panel
                  title="Insight Validation Workflow"
                  icon={<IconCheck size={16} className="text-brand-500" />}
                  headerRight={
                    <div className="flex items-center gap-1 rounded-md bg-bg-secondary p-0.5">
                      <WorkflowTab
                        label="Open"
                        count={openWorkflow.length}
                        active={workflowTab === "open"}
                        onClick={() => setWorkflowTab("open")}
                      />
                      <WorkflowTab
                        label="Reviewed"
                        count={reviewedItems.length}
                        active={workflowTab === "reviewed"}
                        onClick={() => setWorkflowTab("reviewed")}
                      />
                    </div>
                  }
                >
                  {workflowTab === "open" ? (
                    openWorkflow.length === 0 ? (
                      <PanelEmpty text="No insights to review." />
                    ) : (
                      <div className="space-y-2">
                        {openWorkflow.map((item) => (
                          <WorkflowRow
                            key={item.id}
                            item={item}
                            pending={
                              acknowledge.isPending &&
                              acknowledge.variables?.id === item.id
                            }
                            onReview={() => acknowledge.mutate(item)}
                          />
                        ))}
                      </div>
                    )
                  ) : reviewedItems.length === 0 ? (
                    <PanelEmpty text="No reviewed insights yet." />
                  ) : (
                    <div className="space-y-2">
                      {reviewedItems.map((item) => (
                        <ReviewedRow
                          key={item.insightId}
                          item={item}
                          pending={
                            reopen.isPending &&
                            reopen.variables === item.insightId
                          }
                          onReopen={() => reopen.mutate(item.insightId)}
                        />
                      ))}
                    </div>
                  )}
                </Panel>
              </div>
            </div>
          </>
        )}
      </div>
      <AIQuestionResultModal
        open={askModal.open}
        projectId={projectId}
        question={askModal.question}
        source={askModal.source}
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

const TONE_TEXT = {
  danger: "text-danger",
  warning: "text-warning",
  success: "text-success",
  brand: "text-brand-700",
} as const;

function SummaryColumn({
  title,
  tone,
  icon,
  items,
}: {
  title: string;
  tone: keyof typeof TONE_TEXT;
  icon: ReactNode;
  items: string[];
}) {
  return (
    <div>
      <div className={cn("mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold", TONE_TEXT[tone])}>
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
              className="flex gap-1.5 text-[13px] leading-snug text-ink-secondary"
            >
              <span className={cn("mt-1 h-1 w-1 shrink-0 rounded-full", `bg-current ${TONE_TEXT[tone]}`)} />
              <span>{it}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Panel({
  title,
  icon,
  children,
  headerRight,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
  headerRight?: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-line-tertiary bg-bg-primary">
      <div className="flex items-center justify-between gap-2 border-b border-line-tertiary px-4 py-3">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="text-h3 text-ink-primary">{title}</h3>
        </div>
        {headerRight}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function WorkflowTab({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded px-2.5 py-1 text-[12px] font-medium transition-colors",
        active
          ? "bg-bg-primary text-ink-primary shadow-sm"
          : "text-ink-tertiary hover:text-ink-secondary",
      )}
    >
      {label}
      <span className="ml-1 text-ink-tertiary">{count}</span>
    </button>
  );
}

function ReviewedRow({
  item,
  pending,
  onReopen,
}: {
  item: ReviewedInsight;
  pending: boolean;
  onReopen: () => void;
}) {
  const priorityTone =
    PRIORITY_TONE[item.severity as keyof typeof PRIORITY_TONE] ?? "neutral";
  const reviewedAt = item.reviewedAt
    ? new Date(item.reviewedAt).toLocaleDateString()
    : "";
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-line-tertiary px-3 py-2">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-medium text-ink-primary">
            {item.title || item.insightId}
          </span>
          {item.severity && (
            <Badge tone={priorityTone} size="sm">
              {item.severity}
            </Badge>
          )}
        </div>
        {item.summary && (
          <div className="mt-0.5 truncate text-small text-ink-tertiary">
            {item.summary}
          </div>
        )}
        <div className="mt-0.5 text-small text-success">
          Reviewed{item.reviewedByName ? ` by ${item.reviewedByName}` : ""}
          {reviewedAt ? ` · ${reviewedAt}` : ""}
        </div>
      </div>
      <Button
        variant="secondary"
        size="sm"
        onClick={onReopen}
        disabled={pending}
        className="shrink-0"
      >
        {pending ? "Reopening…" : "Reopen"}
      </Button>
    </div>
  );
}

function PanelEmpty({ text }: { text: string }) {
  return <p className="py-2 text-[13px] text-ink-tertiary">{text}</p>;
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

function ChangeRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between gap-2 text-[13px]">
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="rounded-full bg-bg-secondary px-2 py-0.5 text-[12px] font-medium text-ink-primary">
        {value}
      </dd>
    </div>
  );
}

const PRIORITY_TONE = {
  critical: "danger",
  high: "warning",
  medium: "brand",
  low: "neutral",
} as const;

function WorkflowRow({
  item,
  pending,
  onReview,
}: {
  item: InsightWorkflowItem;
  pending: boolean;
  onReview: () => void;
}) {
  const reviewed = item.status === "reviewed";
  const priorityTone =
    PRIORITY_TONE[item.priority as keyof typeof PRIORITY_TONE] ?? "neutral";
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-line-tertiary px-3 py-2">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-medium text-ink-primary">
            {item.title}
          </span>
          {item.priority && (
            <Badge tone={priorityTone} size="sm">
              {item.priority}
            </Badge>
          )}
        </div>
        {item.evidenceSummary && (
          <div className="mt-0.5 truncate text-small text-ink-tertiary">
            {item.evidenceSummary}
          </div>
        )}
        {reviewed && item.acknowledgedBy && (
          <div className="mt-0.5 text-small text-success">
            Reviewed by {item.acknowledgedBy}
          </div>
        )}
      </div>
      {reviewed ? (
        <Badge tone="success" size="md" className="shrink-0">
          <IconCheck size={13} />
          Reviewed
        </Badge>
      ) : (
        <Button
          variant="secondary"
          size="sm"
          onClick={onReview}
          disabled={pending}
          className="shrink-0"
        >
          {pending ? "Saving…" : "Mark reviewed"}
        </Button>
      )}
    </div>
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
