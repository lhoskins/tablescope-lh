"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconChartBar,
  IconCheck,
  IconDatabase,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";
import { useRouter } from "next/navigation";
import { apiClient } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InsightChartBlock } from "@/components/tablescope/home/intelligence-card";
import type { InsightChart } from "@/lib/api/home-intelligence";

export type DashboardDesignerMode =
  | "create"
  | "edit_dashboard"
  | "add_insight"
  | "edit_insight";

type SupportStatus =
  | "fully_supported"
  | "partially_supported"
  | "not_supported";

interface DesignInsight {
  title: string;
  chartType: string;
  businessQuestion: string;
  chart?: InsightChart | null;
  previewData?: { columns?: string[]; rows?: Record<string, unknown>[] };
  status?: string;
  sql?: string;
  labelColumn?: string;
  valueColumn?: string;
}

interface DashboardSuggestion {
  id: string;
  title: string;
  description: string;
  businessPurpose: string;
  audience: string;
  widgets: DesignInsight[];
  kpis: string[];
  dataSources: string[];
  confidence: number;
  qualityScore: number;
  knowledgeGraphContext?: {
    risks?: string[];
    opportunities?: string[];
    gaps?: string[];
  };
  savePayload?: Record<string, unknown>;
}

interface DesignReview {
  supportStatus: SupportStatus;
  supportSummary: string;
  missingRequirements: string[];
  questions: Array<{
    id: string;
    question: string;
    recommended: string;
    options: string[];
  }>;
  chartRecommendations: Array<{
    chartType: string;
    label: string;
    compatible: boolean;
    reason: string;
  }>;
  sources: Array<{
    viewName: string;
    fileName: string;
    columns: Array<{ name: string; type: string }>;
  }>;
  suggestion: DashboardSuggestion | null;
}

interface ApplyResponse {
  dashboard_id: number;
  dashboard_name: string;
  status: "created" | "updated";
}

const PERIODS = [
  ["30_days", "30 days"],
  ["60_days", "60 days"],
  ["90_days", "90 days"],
  ["6_months", "6 months"],
  ["1_year", "1 year"],
  ["2_years", "2 years"],
] as const;

const DESIGN_STEPS = [
  [1, "Describe"],
  [2, "Review AI design"],
  [3, "Preview & create"],
] as const;

const AUDIENCE_LABELS: Record<string, string> = {
  operational: "Operational leaders",
  manager: "Managers",
  executive: "Executives",
  analyst: "Analysts",
};

const EMPHASIS_LABELS: Record<string, string> = {
  balanced_operational_health: "Balanced operational health",
  risk_and_service_levels: "Risk and service levels",
  demand_and_capacity: "Demand and capacity",
  cost_and_productivity: "Cost and productivity",
};

function modeCopy(mode: DashboardDesignerMode): {
  title: string;
  description: string;
  prompt: string;
  apply: string;
} {
  if (mode === "add_insight") {
    return {
      title: "Add an insight with AI",
      description: "Describe one additional KPI card or chart. The rest of the dashboard will not change.",
      prompt: "What additional decision or question should this dashboard answer?",
      apply: "Add insight",
    };
  }
  if (mode === "edit_insight") {
    return {
      title: "Modify this insight with AI",
      description: "Describe the change. AI will replace only the selected card or chart.",
      prompt: "What should this insight show instead?",
      apply: "Replace insight",
    };
  }
  if (mode === "edit_dashboard") {
    return {
      title: "Edit dashboard with AI",
      description: "Describe the operational change and review the complete result before it is applied.",
      prompt: "What should change about this dashboard?",
      apply: "Apply dashboard changes",
    };
  }
  return {
    title: "Create a ServiceNow-style dashboard",
    description: "Describe the decisions people need to make. AI designs, validates and wires the dashboard.",
    prompt: "What do you want people to understand or act on?",
    apply: "Create dashboard",
  };
}

/**
 * Turns an enumerated list of specific charts into an explicit instruction
 * prepended to the free-text prompt, so "create" requests can name exact
 * charts instead of only describing the dashboard as one paragraph and
 * leaving composition entirely up to the LLM. Falls through to the plain
 * prompt unchanged when no items are provided -- fully backward compatible
 * with the single-textarea flow.
 */
function buildDesignPrompt(basePrompt: string, desiredCharts: string[]): string {
  const items = desiredCharts.map((s) => s.trim()).filter(Boolean);
  if (items.length === 0) return basePrompt.trim();
  const enumerated = [
    `Create exactly one widget for each of the following ${items.length} requested chart(s), in this order. Do not merge multiple items into one widget, and do not add widgets beyond this list unless a KPI summary is explicitly useful alongside them.`,
    ...items.map((item, index) => `${index + 1}. ${item}`),
  ].join("\n");
  const extra = basePrompt.trim();
  return extra ? `${enumerated}\n\n${extra}` : enumerated;
}

function statusPresentation(status: SupportStatus): {
  label: string;
  tone: "success" | "warning" | "danger";
  icon: typeof IconCheck;
} {
  if (status === "fully_supported") {
    return { label: "Fully supported", tone: "success", icon: IconCheck };
  }
  if (status === "partially_supported") {
    return { label: "Partially supported", tone: "warning", icon: IconAlertTriangle };
  }
  return { label: "Not supported", tone: "danger", icon: IconDatabase };
}

export function AIDashboardDesigner({
  open,
  projectId,
  mode = "create",
  dashboardId,
  targetInsightId,
  dashboardGroupId,
  dashboardGroupName,
  initialPrompt = "",
  onClose,
  onApplied,
  notify,
}: {
  open: boolean;
  projectId: string;
  mode?: DashboardDesignerMode;
  dashboardId?: number;
  targetInsightId?: string;
  dashboardGroupId?: number;
  dashboardGroupName?: string;
  initialPrompt?: string;
  onClose: () => void;
  onApplied: (dashboardId: number) => void;
  notify: (message: string, tone?: "success" | "error" | "info") => void;
}) {
  const router = useRouter();
  const copy = modeCopy(mode);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [prompt, setPrompt] = useState(initialPrompt);
  // Only meaningful in "create" mode -- an explicit, growable list of exact
  // charts the user wants, as an alternative to describing the whole
  // dashboard as one paragraph and hoping the LLM's composition matches.
  const [desiredCharts, setDesiredCharts] = useState<string[]>([""]);
  const [audience, setAudience] = useState("operational");
  const [emphasis, setEmphasis] = useState("balanced_operational_health");
  const [period, setPeriod] = useState("1_year");
  const [dimensionLabel, setDimensionLabel] = useState("Site");
  const [review, setReview] = useState<DesignReview | null>(null);
  const [acceptPartial, setAcceptPartial] = useState(false);

  useEffect(() => {
    if (!open) return;
    setStep(1);
    setPrompt(initialPrompt);
    setDesiredCharts([""]);
    setReview(null);
    setAcceptPartial(false);
  }, [initialPrompt, mode, open]);

  const requestedChartCount = useMemo(
    () => (mode === "create" ? desiredCharts.map((s) => s.trim()).filter(Boolean).length : 0),
    [desiredCharts, mode],
  );

  const effectivePrompt = useMemo(
    () => (mode === "create" ? buildDesignPrompt(prompt, desiredCharts) : prompt.trim()),
    [desiredCharts, mode, prompt],
  );

  const requestBody = useMemo(
    () => ({
      project_id: Number(projectId),
      prompt: effectivePrompt,
      mode,
      dashboard_id: dashboardId,
      target_insight_id: targetInsightId,
      audience,
      emphasis,
      period,
      dimension_label: dimensionLabel.trim() || "Dimension",
      dashboard_group_id: dashboardGroupId,
    }),
    [audience, dashboardGroupId, dashboardId, dimensionLabel, effectivePrompt, emphasis, mode, period, projectId, targetInsightId],
  );

  const reviewMutation = useMutation({
    mutationFn: () =>
      apiClient.post<DesignReview>(
        "/api/ai/actions/dashboard-designer/review",
        requestBody,
      ),
    onSuccess: (response) => {
      setReview(response);
      setAcceptPartial(false);
      setStep(2);
    },
    onError: (error: Error) => notify(error.message, "error"),
  });

  const applyMutation = useMutation({
    mutationFn: () => {
      if (!review?.suggestion) throw new Error("There is no validated design to apply.");
      return apiClient.post<ApplyResponse>(
        "/api/ai/actions/dashboard-designer/apply",
        {
          project_id: Number(projectId),
          prompt: effectivePrompt,
          mode,
          dashboard_id: dashboardId,
          target_insight_id: targetInsightId,
          dashboard_group_id: dashboardGroupId,
          audience,
          emphasis,
          period,
          dimension_label: dimensionLabel.trim() || "Dimension",
          support_status: review.supportStatus,
          accept_partial: acceptPartial,
          suggestion: review.suggestion,
        },
      );
    },
    onSuccess: (response) => {
      notify(
        response.status === "created"
          ? `Created “${response.dashboard_name}”`
          : `Updated “${response.dashboard_name}”`,
        "success",
      );
      onApplied(response.dashboard_id);
    },
    onError: (error: Error) => notify(error.message, "error"),
  });

  if (!open) return null;
  const canPreview =
    review?.supportStatus === "fully_supported" ||
    (review?.supportStatus === "partially_supported" && acceptPartial);

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/35 p-3 sm:p-5">
      <div className="mx-auto my-3 w-full max-w-7xl rounded-xl border border-line-tertiary bg-bg-primary shadow-xl">
        <header className="flex flex-col gap-3 border-b border-line-tertiary px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-5">
          <div>
            <div className="flex items-center gap-2">
              <IconSparkles size={18} className="text-ai" />
              <h2 className="text-h2 text-ink-primary">{copy.title}</h2>
              <Badge tone="ai">No configuration</Badge>
            </div>
            <p className="mt-1 text-small text-ink-tertiary">{copy.description}</p>
            {dashboardGroupName && (
              <p className="mt-1 text-[11px] text-ink-tertiary">
                Dashboard group: {dashboardGroupName}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close AI dashboard designer"
            className="self-end rounded p-1 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary sm:self-start"
          >
            <IconX size={18} />
          </button>
        </header>

        <nav className="flex flex-wrap gap-2 border-b border-line-tertiary px-4 py-3 sm:px-5" aria-label="Dashboard creation steps">
          {DESIGN_STEPS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              disabled={value > step || (value === 3 && !canPreview)}
              onClick={() => setStep(value)}
              className={`rounded-full border px-3 py-1.5 text-[11px] font-medium ${
                step === value
                  ? "border-brand-600 bg-brand-600 text-white"
                  : "border-line-secondary bg-bg-primary text-ink-secondary"
              } disabled:cursor-not-allowed disabled:opacity-50`}
            >
              {value}. {label}
            </button>
          ))}
        </nav>

        {step === 1 && (
          <section className="p-4 sm:p-5">
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(300px,.65fr)]">
              <Card className="p-4">
                {mode === "create" && (
                  <div className="mb-4">
                    <div className="text-h3 text-ink-primary">Specific charts (optional)</div>
                    <p className="mt-1 text-small text-ink-tertiary">
                      Name exact charts you want instead of leaving composition entirely to AI. Each line becomes
                      one widget.
                    </p>
                    <div className="mt-3 space-y-2">
                      {desiredCharts.map((item, index) => (
                        <div key={index} className="flex items-center gap-2">
                          <input
                            value={item}
                            onChange={(event) => {
                              const next = [...desiredCharts];
                              next[index] = event.target.value;
                              setDesiredCharts(next);
                            }}
                            placeholder={
                              index === 0
                                ? "Example: Vendor spend trend over time"
                                : "Example: High-priority incidents by priority"
                            }
                            className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
                          />
                          {desiredCharts.length > 1 && (
                            <button
                              type="button"
                              onClick={() => setDesiredCharts(desiredCharts.filter((_, i) => i !== index))}
                              aria-label="Remove this chart"
                              className="shrink-0 rounded p-1.5 text-ink-tertiary hover:bg-bg-secondary hover:text-red-600"
                            >
                              <IconX size={14} />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                    <Button
                      size="sm"
                      variant="secondary"
                      className="mt-2"
                      onClick={() => setDesiredCharts([...desiredCharts, ""])}
                    >
                      + Add another chart
                    </Button>
                  </div>
                )}

                <label htmlFor="ai-dashboard-request" className="text-h3 text-ink-primary">
                  {mode === "create" && requestedChartCount > 0 ? "Additional context (optional)" : copy.prompt}
                </label>
                <p className="mt-1 text-small text-ink-tertiary">
                  Use business language. AI selects the metrics, queries, calculations and compatible charts.
                </p>
                <textarea
                  id="ai-dashboard-request"
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  rows={mode === "create" && requestedChartCount > 0 ? 3 : 7}
                  placeholder="Example: Show demand versus resolution capacity, backlog and SLA risk, the sites driving breaches, and the best improvement opportunities."
                  className="mt-3 w-full resize-y rounded-md border border-line-secondary bg-bg-primary p-3 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
                />
                {mode === "create" && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {[
                      "Show where backlog and SLA risk are increasing, what is driving it, and what managers should do next.",
                      "Compare incoming demand with completed work and highlight teams with capacity gaps.",
                      "Create an executive request view covering volume, fulfillment speed, overdue work and service levels.",
                    ].map((suggestion, index) => (
                      <Button key={suggestion} size="sm" variant="secondary" onClick={() => setPrompt(suggestion)}>
                        {index === 0 ? "Backlog & SLA risk" : index === 1 ? "Demand vs capacity" : "Executive request view"}
                      </Button>
                    ))}
                  </div>
                )}
              </Card>

              <Card className="p-4">
                <h3 className="text-h3 text-ink-primary">Creation context</h3>
                <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                  <label className="text-small font-medium text-ink-secondary">
                    Audience
                    <select value={audience} onChange={(event) => setAudience(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]">
                      {Object.entries(AUDIENCE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                  <label className="text-small font-medium text-ink-secondary">
                    Default period
                    <select value={period} onChange={(event) => setPeriod(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]">
                      {PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                  <label className="text-small font-medium text-ink-secondary">
                    Primary dimension
                    <input value={dimensionLabel} onChange={(event) => setDimensionLabel(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]" />
                  </label>
                  <label className="text-small font-medium text-ink-secondary">
                    Operational emphasis
                    <select value={emphasis} onChange={(event) => setEmphasis(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]">
                      {Object.entries(EMPHASIS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                </div>
                <p className="mt-3 text-[11px] leading-4 text-ink-tertiary">
                  Tablescope profiles authorized data, validates generated SQL, saves governed queries and adds lineage automatically.
                </p>
              </Card>
            </div>
            <div className="mt-4 flex justify-end">
              <Button variant="primary" disabled={effectivePrompt.length < 3 || reviewMutation.isPending} onClick={() => reviewMutation.mutate()}>
                <IconSparkles size={14} />
                {reviewMutation.isPending ? "Analyzing project data…" : "Analyze data & propose design"}
              </Button>
            </div>
          </section>
        )}

        {step === 2 && review && (
          <section className="p-4 sm:p-5">
            {requestedChartCount > 0 && (
              <p className="mb-3 text-[11px] text-ink-tertiary">
                Requested {requestedChartCount} chart{requestedChartCount === 1 ? "" : "s"}; AI proposed{" "}
                {review.suggestion?.widgets.length ?? 0}.
                {(review.suggestion?.widgets.length ?? 0) !== requestedChartCount &&
                  " A mismatch usually means one request couldn't be grounded in the available data, or two were combined -- check the preview below."}
              </p>
            )}
            <SupportReview
              review={review}
              audience={audience}
              emphasis={emphasis}
              acceptPartial={acceptPartial}
              onAudience={setAudience}
              onEmphasis={setEmphasis}
              onAcceptPartial={setAcceptPartial}
              onAddData={() => router.push(`/projects/${projectId}/data-sources?return=dashboards`)}
              onSaveRequest={() => {
                window.sessionStorage.setItem(`dashboard-request:${projectId}`, effectivePrompt);
                notify("Dashboard request saved until supporting data is added", "info");
              }}
            />
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button variant="secondary" onClick={() => setStep(1)}><IconArrowLeft size={13} />Back</Button>
              {review.supportStatus !== "not_supported" && (
                <Button variant="secondary" disabled={reviewMutation.isPending} onClick={() => reviewMutation.mutate()}>
                  <IconSparkles size={13} />Reanalyze answers
                </Button>
              )}
              <Button variant="primary" disabled={!canPreview} onClick={() => setStep(3)}>
                Preview ServiceNow-style dashboard
              </Button>
            </div>
          </section>
        )}

        {step === 3 && review?.suggestion && (
          <section className="p-3 sm:p-4">
            <OperationalDashboardPreview
              suggestion={review.suggestion}
              period={PERIODS.find(([value]) => value === period)?.[1] ?? period}
              dimension={dimensionLabel}
              compact={mode === "add_insight" || mode === "edit_insight"}
            />
            <div className="mt-4 flex flex-wrap justify-end gap-2 px-1 pb-1">
              <Button variant="secondary" onClick={() => setStep(2)}><IconArrowLeft size={13} />Refine with AI</Button>
              <Button variant="primary" disabled={applyMutation.isPending} onClick={() => applyMutation.mutate()}>
                <IconCheck size={14} />
                {applyMutation.isPending ? "Applying validated design…" : copy.apply}
              </Button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function SupportReview({
  review,
  audience,
  emphasis,
  acceptPartial,
  onAudience,
  onEmphasis,
  onAcceptPartial,
  onAddData,
  onSaveRequest,
}: {
  review: DesignReview;
  audience: string;
  emphasis: string;
  acceptPartial: boolean;
  onAudience: (value: string) => void;
  onEmphasis: (value: string) => void;
  onAcceptPartial: (value: boolean) => void;
  onAddData: () => void;
  onSaveRequest: () => void;
}) {
  const status = statusPresentation(review.supportStatus);
  const StatusIcon = status.icon;
  const compatibleCharts = review.chartRecommendations.filter((chart) => chart.compatible);
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,.85fr)]">
      <div className="space-y-4">
        <Card className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <StatusIcon size={17} />
                <h3 className="text-h3 text-ink-primary">Data readiness</h3>
              </div>
              <p className="mt-1 text-small text-ink-secondary">{review.supportSummary}</p>
            </div>
            <Badge tone={status.tone}>{status.label}</Badge>
          </div>
          {review.missingRequirements.length > 0 && (
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3">
              <div className="text-small font-medium text-amber-900">Additional data required</div>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-[11px] text-amber-800">
                {review.missingRequirements.map((requirement) => <li key={requirement}>{requirement}</li>)}
              </ul>
            </div>
          )}
          {review.supportStatus === "partially_supported" && (
            <label className="mt-3 flex items-start gap-2 text-small text-ink-secondary">
              <input type="checkbox" checked={acceptPartial} onChange={(event) => onAcceptPartial(event.target.checked)} className="mt-0.5" />
              Create only the validated insights now and keep the unsupported requirements out of the published dashboard.
            </label>
          )}
          {review.supportStatus === "not_supported" && (
            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="primary" onClick={onAddData}><IconDatabase size={14} />Upload or connect data</Button>
              <Button variant="secondary" onClick={onSaveRequest}>Save dashboard request</Button>
            </div>
          )}
        </Card>

        {review.supportStatus !== "not_supported" && (
          <Card className="p-4">
            <h3 className="text-h3 text-ink-primary">AI design questions</h3>
            <p className="mt-1 text-small text-ink-tertiary">These choices change the operational story—not individual chart configuration.</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="text-small font-medium text-ink-secondary">
                Who should use this dashboard?
                <select value={audience} onChange={(event) => onAudience(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]">
                  {Object.entries(AUDIENCE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <label className="text-small font-medium text-ink-secondary">
                What should the story emphasize?
                <select value={emphasis} onChange={(event) => onEmphasis(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px]">
                  {Object.entries(EMPHASIS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
            </div>
          </Card>
        )}
      </div>

      <div className="space-y-4">
        <Card className="p-4">
          <h3 className="text-h3 text-ink-primary">Charts compatible with this data</h3>
          <p className="mt-1 text-small text-ink-tertiary">Only presentations supported by the detected field shape are offered.</p>
          <div className="mt-3 space-y-2">
            {compatibleCharts.map((chart) => (
              <div key={chart.chartType} className="flex items-start gap-2 border-b border-line-tertiary pb-2 last:border-0 last:pb-0">
                <IconChartBar size={15} className="mt-0.5 shrink-0 text-brand-600" />
                <div className="min-w-0 flex-1">
                  <div className="text-small font-medium text-ink-primary">{chart.label}</div>
                  <div className="text-[11px] text-ink-tertiary">{chart.reason}</div>
                </div>
                <Badge tone="success">Compatible</Badge>
              </div>
            ))}
          </div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-h3 text-ink-primary">Grounded project data</h3>
            <Badge tone="neutral">{review.sources.length} sources</Badge>
          </div>
          <div className="mt-3 space-y-2">
            {review.sources.slice(0, 6).map((source) => (
              <div key={source.viewName} className="flex items-center justify-between gap-3 text-small">
                <span className="min-w-0 truncate text-ink-secondary">{source.fileName}</span>
                <span className="shrink-0 text-[11px] text-ink-tertiary">{source.columns.length} fields</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function OperationalDashboardPreview({
  suggestion,
  period,
  dimension,
  compact,
}: {
  suggestion: DashboardSuggestion;
  period: string;
  dimension: string;
  compact: boolean;
}) {
  const context = suggestion.knowledgeGraphContext;
  const briefItems = [
    context?.risks?.[0] || "AI will summarize the highest validated operational risk.",
    context?.gaps?.[0] || "AI will identify the primary data-backed driver.",
    context?.opportunities?.[0] || "AI will recommend the highest-impact action.",
  ];
  const valid = suggestion.widgets.filter((insight) => insight.status === "valid");
  const kpis = valid.filter((insight) => insight.chartType === "kpi");
  const charts = valid.filter((insight) => insight.chartType !== "kpi");
  return (
    <div className="rounded-xl bg-bg-secondary/50 p-3 sm:p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-h2 text-ink-primary">{suggestion.title}</h2>
            <Badge tone="ai">Preview</Badge>
          </div>
          <p className="mt-0.5 text-[11px] text-ink-tertiary">Operational patterns, contributors and recommended actions</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="rounded-md border border-line-secondary bg-bg-primary px-2.5 py-1 text-[11px] text-ink-secondary">Period: {period}</span>
          <span className="rounded-md border border-line-secondary bg-bg-primary px-2.5 py-1 text-[11px] text-ink-secondary">{dimension}: All</span>
        </div>
      </div>

      {!compact && (
        <div className="mt-3 border-y border-line-tertiary py-3">
          <div className="text-small font-semibold text-ink-primary">Operational brief</div>
          <div className="mt-2 grid gap-3 lg:grid-cols-3">
            {briefItems.map((item, index) => (
              <div key={`${index}-${item}`} className="flex gap-2 text-[11px] text-ink-secondary">
                <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${index === 0 ? "bg-red-500" : index === 1 ? "bg-amber-500" : "bg-emerald-500"}`} />
                <div><span className="font-semibold text-ink-primary">{index === 0 ? "Risk" : index === 1 ? "Primary driver" : "Recommended action"}</span><div className="mt-0.5">{item}</div></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {!compact && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(kpis.length > 0 ? kpis.slice(0, 4) : suggestion.kpis.slice(0, 4).map((title) => ({ title, businessQuestion: "Calculated from validated data when created", chartType: "kpi", status: "valid" } as DesignInsight))).map((insight) => (
            <Card key={insight.title} className="min-h-[92px] p-3">
              <div className="text-[10px] font-semibold uppercase text-ink-tertiary">{insight.title}</div>
              {insight.chart ? <InsightChartBlock chart={insight.chart} /> : <div className="mt-3 text-[11px] text-ink-tertiary">{insight.businessQuestion}</div>}
            </Card>
          ))}
        </div>
      )}

      <div className={`mt-3 grid gap-3 ${compact ? "grid-cols-1" : "lg:grid-cols-2"}`}>
        {(compact ? valid.slice(0, 1) : charts).map((insight, index) => (
          <Card key={`${insight.title}-${index}`} className={`p-3 ${!compact && index === 0 ? "lg:col-span-2" : ""}`}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-small font-semibold text-ink-primary">{insight.title}</div>
                <div className="mt-0.5 text-[11px] text-ink-tertiary">{insight.businessQuestion}</div>
              </div>
              <Badge tone="neutral">{insight.chartType.replaceAll("_", " ")}</Badge>
            </div>
            <div className="mt-2 min-h-[130px]">
              {insight.chart ? <InsightChartBlock chart={insight.chart} /> : <PreviewTable insight={insight} />}
            </div>
          </Card>
        ))}
      </div>

      {!compact && (
        <Card className="mt-3 p-3">
          <div className="text-small font-semibold text-ink-primary">Best improvement opportunities</div>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            {briefItems.map((item, index) => <div key={`${index}-${item}`} className="text-[11px] text-ink-secondary"><span className="mr-1 font-semibold text-brand-600">{index + 1}.</span>{item}</div>)}
          </div>
        </Card>
      )}
    </div>
  );
}

function PreviewTable({ insight }: { insight: DesignInsight }) {
  const columns = insight.previewData?.columns ?? [];
  const rows = insight.previewData?.rows ?? [];
  if (columns.length === 0 || rows.length === 0) {
    return <div className="grid min-h-[130px] place-items-center text-small text-ink-tertiary">Validated query preview</div>;
  }
  return (
    <div className="max-h-[190px] overflow-auto">
      <table className="w-full text-[11px]">
        <thead><tr>{columns.map((column) => <th key={column} className="border-b border-line-tertiary px-2 py-1 text-left font-medium text-ink-secondary">{column}</th>)}</tr></thead>
        <tbody>{rows.slice(0, 8).map((row, index) => <tr key={index}>{columns.map((column) => <td key={column} className="border-b border-line-tertiary px-2 py-1 text-ink-primary">{row[column] == null ? "" : String(row[column])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
