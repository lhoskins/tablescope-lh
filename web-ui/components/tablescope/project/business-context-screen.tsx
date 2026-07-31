"use client";

import { useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  IconChartLine,
  IconChevronDown,
  IconChevronRight,
  IconClock,
  IconGauge,
  IconMinus,
  IconPencil,
  IconPlus,
  IconRefresh,
  IconTarget,
  IconTrash,
  IconTrendingDown,
  IconTrendingUp,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import {
  getProjectContext,
  createGoal,
  updateGoal,
  deleteGoal,
  createMetric,
  updateMetric,
  deleteMetric,
  createRisk,
  updateRisk,
  deleteRisk,
  startKpiSourceMatch,
  type ProjectContext,
  type ProjectGoal,
  type ProjectMetric,
  type ProjectRisk,
  type MetricCreateRequest,
} from "@/lib/api/project-context";
import { useProjectMembers, type ProjectMember } from "@/lib/ui/use-project-data";

const GOAL_STATUSES = ["not_started", "in_progress", "at_risk", "achieved", "cancelled"];
const RISK_LIKELIHOOD = ["rare", "unlikely", "possible", "likely", "almost_certain"];
const RISK_IMPACT = ["negligible", "insignificant", "minor", "moderate", "major", "severe", "catastrophic"];
const RISK_STATUSES = ["open", "mitigating", "monitoring", "mitigated", "closed", "accepted"];
const METRIC_DIRECTIONALITY = [
  { value: "higher_is_better", label: "Higher is better" },
  { value: "lower_is_better", label: "Lower is better" },
  { value: "neutral", label: "Neutral" },
];
function fmtDate(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  return Number.isNaN(d.getTime())
    ? ts
    : d.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function fmtDateShort(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  return Number.isNaN(d.getTime())
    ? ts
    : d.toLocaleDateString(undefined, { month: "2-digit", day: "2-digit", year: "numeric" });
}

function fmtNumber(value: number | null | undefined, format?: string | null, unit?: string | null): string {
  if (value == null) return "—";
  let text: string;
  if (format === "percent") {
    text = `${(value * 100).toFixed(1)}%`;
  } else if (format === "currency") {
    text = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);
  } else {
    text = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
  }
  return unit ? `${text} ${unit}` : text;
}

function metricProgress(metric: ProjectMetric): number {
  const target = metric.targets?.find((t) => t.active && t.status !== "archived");
  const current = metric.latest_value != null ? Number(metric.latest_value) : null;
  const targetValue = target?.target_value != null ? Number(target.target_value) : null;
  if (current == null || targetValue == null || targetValue === 0) return 0;
  const ratio = metric.directionality === "lower_is_better" ? targetValue / current : current / targetValue;
  return Math.min(Math.max(Math.round(ratio * 100), 0), 100);
}

function metricOnTrack(metric: ProjectMetric): boolean {
  const target = metric.targets?.find((t) => t.active && t.status !== "archived");
  const current = metric.latest_value != null ? Number(metric.latest_value) : null;
  const targetValue = target?.target_value != null ? Number(target.target_value) : null;
  if (current == null || targetValue == null) return false;
  if (metric.directionality === "lower_is_better") return current <= targetValue;
  if (metric.directionality === "higher_is_better") return current >= targetValue;
  return current === targetValue;
}

function metricTrend(metric: ProjectMetric): "up" | "down" | "flat" {
  const meta = metricTrendMeta(metric);
  return meta.direction;
}

function metricTrendMeta(metric: ProjectMetric): { direction: "up" | "down" | "flat"; label: string; tone: BadgeProps["tone"] } {
  const target = metric.targets?.find((t) => t.active && t.status !== "archived");
  const current = metric.latest_value != null ? Number(metric.latest_value) : null;
  const targetValue = target?.target_value != null ? Number(target.target_value) : null;
  if (current == null || targetValue == null) return { direction: "flat", label: "—", tone: "neutral" };
  let onTrack = false;
  if (metric.directionality === "lower_is_better") onTrack = current <= targetValue;
  else if (metric.directionality === "higher_is_better") onTrack = current >= targetValue;
  else onTrack = current === targetValue;
  if (onTrack) {
    return { direction: "up", label: "Improving", tone: "success" };
  }
  return { direction: "down", label: "Watch", tone: "warning" };
}

function goalProgress(goal: ProjectGoal, metrics: ProjectMetric[]): number {
  const children = metrics.filter((m) => m.success_criterion_id === goal.id);
  if (children.length === 0) return 0;
  const total = children.reduce((sum, m) => sum + metricProgress(m), 0);
  return Math.round(total / children.length);
}

function goalOnTrack(goal: ProjectGoal, metrics: ProjectMetric[]): boolean {
  const children = metrics.filter((m) => m.success_criterion_id === goal.id);
  if (children.length === 0) return false;
  return children.every((m) => metricOnTrack(m));
}

function goalDeleteImpact(
  goalId: number | null,
  goals: ProjectGoal[],
  metrics: ProjectMetric[],
  risks: ProjectRisk[],
): string {
  if (!goalId) {
    return "This will archive the success criterion.";
  }
  const goal = goals.find((g) => g.id === goalId);
  if (!goal) {
    return "This will archive the success criterion.";
  }
  const otherGoals = goals.filter(
    (g) => g.id !== goal.id && g.active,
  );
  const linkedMetrics = metrics.filter((m) =>
    m.active && goal.linked_metric_ids.includes(m.id),
  );
  const exclusiveMetrics = linkedMetrics.filter((m) =>
    !otherGoals.some((g) => g.linked_metric_ids.includes(m.id)),
  );
  const exclusiveRisks = risks.filter(
    (r) =>
      r.active &&
      r.linked_goal_ids.length === 1 &&
      r.linked_goal_ids.includes(goal.id),
  );
  const dataMatches = exclusiveMetrics.filter(
    (m) => m.source_match_status === "matched",
  ).length;

  const parts: string[] = [];
  if (exclusiveMetrics.length > 0) {
    parts.push(
      `${exclusiveMetrics.length} linked measure${exclusiveMetrics.length === 1 ? "" : "s"}`,
    );
  }
  if (exclusiveRisks.length > 0) {
    parts.push(
      `${exclusiveRisks.length} linked risk${exclusiveRisks.length === 1 ? "" : "s"}`,
    );
  }
  if (dataMatches > 0) {
    parts.push(`${dataMatches} data match${dataMatches === 1 ? "" : "es"}`);
  }

  if (parts.length === 0) {
    return "This will archive the success criterion. Linked measures and risks will remain available.";
  }
  return `This will archive the success criterion and the following linked items: ${parts.join(", ")}.`;
}

function goalStatusTone(status: string): BadgeProps["tone"] {
  switch (status) {
    case "achieved":
      return "success";
    case "in_progress":
      return "brand";
    case "at_risk":
      return "danger";
    default:
      return "neutral";
  }
}

function riskSeverityTone(severity: string | null | undefined): BadgeProps["tone"] {
  switch (severity) {
    case "critical":
      return "danger";
    case "high":
      return "warning";
    case "medium":
      return "brand";
    default:
      return "success";
  }
}

function riskStatusTone(status: string): BadgeProps["tone"] {
  switch (status) {
    case "open":
      return "danger";
    case "mitigating":
      return "warning";
    case "monitoring":
      return "brand";
    case "closed":
    case "mitigated":
      return "success";
    default:
      return "neutral";
  }
}

function matchStatusTone(status: string | null | undefined): BadgeProps["tone"] {
  switch (status) {
    case "matched":
      return "success";
    case "candidate_found":
    case "validated":
      return "warning";
    case "searching":
      return "brand";
    case "error":
    case "no_match":
      return "danger";
    default:
      return "outline";
  }
}

function likelihoodTone(likelihood: string | null | undefined): BadgeProps["tone"] {
  switch (likelihood) {
    case "rare":
    case "unlikely":
      return "success";
    case "possible":
      return "brand";
    case "likely":
      return "warning";
    case "almost_certain":
      return "danger";
    default:
      return "neutral";
  }
}

function impactTone(impact: string | null | undefined): BadgeProps["tone"] {
  switch (impact) {
    case "negligible":
    case "insignificant":
    case "minor":
      return "success";
    case "moderate":
      return "brand";
    case "major":
      return "warning";
    case "severe":
    case "catastrophic":
      return "danger";
    default:
      return "neutral";
  }
}

function displayName(memberMap: Map<number, ProjectMember>, userId: number | null | undefined): string {
  if (userId == null) return "—";
  const member = memberMap.get(userId);
  if (member?.display_name) return member.display_name;
  if (member?.email) return member.email;
  return `User ${userId}`;
}

function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function formatTarget(
  value: number | null | undefined,
  directionality: string | null | undefined,
  format?: string | null,
  unit?: string | null
): string {
  if (value == null) return "—";
  const op = directionality === "lower_is_better" ? "≤ " : directionality === "higher_is_better" ? "≥ " : "";
  return op + fmtNumber(value, format, unit);
}

function metricIcon(metricId: number) {
  const icons = [
    <IconChartLine key="chart" size={18} className="text-brand" />,
    <IconClock key="clock" size={18} className="text-warning" />,
    <IconGauge key="gauge" size={18} className="text-success" />,
  ];
  return icons[metricId % icons.length];
}

export function BusinessContextScreen({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const { toasts, push, dismiss } = useToasts();

  const contextQueryKey = ["project-context", projectId];
  const { data, isLoading, refetch } = useQuery<ProjectContext>({
    queryKey: contextQueryKey,
    queryFn: () => getProjectContext(projectId),
  });

  const membersQuery = useProjectMembers(projectId);
  const memberMap = useMemo(() => {
    const map = new Map<number, ProjectMember>();
    for (const m of membersQuery.data ?? []) {
      map.set(m.user_id, m);
    }
    return map;
  }, [membersQuery.data]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: contextQueryKey });
    void refetch();
  };

  const onError = (e: unknown) => {
    push(e instanceof Error ? e.message : "An unexpected error occurred", "error");
  };

  const goalCreate = useMutation({
    mutationFn: createGoal.bind(null, projectId),
    onSuccess: () => { push("Success criterion created", "success"); refresh(); },
    onError,
  });
  const goalUpdate = useMutation({
    mutationFn: (args: { goalId: number; body: Parameters<typeof updateGoal>[2] }) =>
      updateGoal(projectId, args.goalId, args.body),
    onSuccess: () => { push("Success criterion updated", "success"); refresh(); },
    onError,
  });
  const goalDelete = useMutation({
    mutationFn: deleteGoal.bind(null, projectId),
    onSuccess: () => { push("Success criterion deleted", "success"); refresh(); },
    onError,
  });

  const metricCreate = useMutation({
    mutationFn: createMetric.bind(null, projectId),
    onSuccess: () => { push("KPI created", "success"); refresh(); },
    onError,
  });
  const metricUpdate = useMutation({
    mutationFn: (args: { metricId: number; body: Parameters<typeof updateMetric>[2] }) =>
      updateMetric(projectId, args.metricId, args.body),
    onSuccess: () => { push("KPI updated", "success"); refresh(); },
    onError,
  });
  const metricDelete = useMutation({
    mutationFn: deleteMetric.bind(null, projectId),
    onSuccess: () => { push("KPI deleted", "success"); refresh(); },
    onError,
  });

  const riskCreate = useMutation({
    mutationFn: createRisk.bind(null, projectId),
    onSuccess: () => { push("Risk created", "success"); refresh(); },
    onError,
  });
  const riskUpdate = useMutation({
    mutationFn: (args: { riskId: number; body: Parameters<typeof updateRisk>[2] }) =>
      updateRisk(projectId, args.riskId, args.body),
    onSuccess: () => { push("Risk updated", "success"); refresh(); },
    onError,
  });
  const riskDelete = useMutation({
    mutationFn: deleteRisk.bind(null, projectId),
    onSuccess: () => { push("Risk deleted", "success"); refresh(); },
    onError,
  });

  const kpiMatch = useMutation({
    mutationFn: (metricId: number) => startKpiSourceMatch(projectId, metricId),
    onSuccess: (res) => push(res.message, "success"),
    onError,
  });

  const canEdit = data?.permissions.can_edit ?? false;

  const goals = data?.goals ?? [];
  const metrics = data?.metrics ?? [];
  const risks = data?.risks ?? [];

  const onTrackCount = metrics.filter((m) => metricOnTrack(m)).length;
  const onTrackPercent = metrics.length ? Math.round((onTrackCount / metrics.length) * 100) : 0;

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-business-context"
      breadcrumbLabel="Goals"
      actions={
        <Button variant="secondary" size="sm" onClick={() => void refetch()}>
          <IconRefresh size={14} />
          Refresh
        </Button>
      }
    >
      <div className="space-y-6">
        {!isLoading && (
          <div>
            <h1 className="text-2xl font-semibold text-ink-primary">Goals</h1>
            <p className="mt-1 text-sm text-ink-secondary">
              Define project success, track the KPIs that prove it, and manage project-wide risks.
            </p>
          </div>
        )}
        {isLoading ? (
          <Card>
            <CardBody>
              <div className="text-sm text-ink-secondary">Loading goals…</div>
            </CardBody>
          </Card>
        ) : (
          <>
            <SummaryCards
              goalCount={goals.length}
              kpiCount={metrics.length}
              riskCount={risks.length}
              onTrackPercent={onTrackPercent}
            />

            <SuccessCriteriaSection
              goals={goals}
              metrics={metrics}
              risks={risks}
              memberMap={memberMap}
              canEdit={canEdit}
              onCreateGoal={(body) => goalCreate.mutate(body)}
              onUpdateGoal={(id, body) => goalUpdate.mutate({ goalId: id, body })}
              onDeleteGoal={(id) => goalDelete.mutate(id)}
              onCreateMetric={(body) => metricCreate.mutate(body)}
              onUpdateMetric={(id, body) => metricUpdate.mutate({ metricId: id, body })}
              onDeleteMetric={(id) => metricDelete.mutate(id)}
              onMatchMetric={(metricId) => kpiMatch.mutate(metricId)}
            />

            <RisksSection
              risks={risks}
              memberMap={memberMap}
              canEdit={canEdit}
              onCreateRisk={(body) => riskCreate.mutate(body)}
              onUpdateRisk={(id, body) => riskUpdate.mutate({ riskId: id, body })}
              onDeleteRisk={(id) => riskDelete.mutate(id)}
            />
          </>
        )}
      </div>
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}

function SummaryCards({
  goalCount,
  kpiCount,
  riskCount,
  onTrackPercent,
}: {
  goalCount: number;
  kpiCount: number;
  riskCount: number;
  onTrackPercent: number;
}) {
  return (
    <Card>
      <CardBody className="p-0">
        <div className="grid grid-cols-1 divide-y divide-line-tertiary sm:grid-cols-2 sm:divide-y-0 sm:divide-x lg:grid-cols-4">
          <div className="flex items-center gap-3 px-6 py-4">
            <span className="text-3xl font-semibold text-ink-primary">{goalCount}</span>
            <span className="text-sm text-ink-secondary">Success criteria</span>
          </div>
          <div className="flex items-center gap-3 px-6 py-4">
            <span className="text-3xl font-semibold text-ink-primary">{kpiCount}</span>
            <span className="text-sm text-ink-secondary">KPIs</span>
          </div>
          <div className="flex items-center gap-3 px-6 py-4">
            <span className="text-3xl font-semibold text-ink-primary">{riskCount}</span>
            <span className="text-sm text-ink-secondary">Project risks</span>
          </div>
          <div className="flex items-center gap-3 px-6 py-4">
            <span className="text-3xl font-semibold text-ink-primary">{onTrackPercent}%</span>
            <span className="text-sm text-ink-secondary">On track</span>
            <div className="ml-auto h-2 w-24 overflow-hidden rounded-full bg-bg-secondary">
              <div className="h-full rounded-full bg-success" style={{ width: `${onTrackPercent}%` }} />
            </div>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

interface KpiDraftState {
  id?: number;
  name?: string;
  description?: string | null;
  latest_value?: number | null;
  target_value?: number | null;
  directionality?: string;
  cadence?: string | null;
  unit?: string | null;
  format?: string | null;
  owner_id?: number | null;
  version?: number;
}

interface SuccessCriteriaSectionProps {
  goals: ProjectGoal[];
  metrics: ProjectMetric[];
  risks: ProjectRisk[];
  memberMap: Map<number, ProjectMember>;
  canEdit: boolean;
  onCreateGoal: (body: Parameters<typeof createGoal>[1]) => void;
  onUpdateGoal: (id: number, body: Parameters<typeof updateGoal>[2]) => void;
  onDeleteGoal: (id: number) => void;
  onCreateMetric: (body: Parameters<typeof createMetric>[1]) => void;
  onUpdateMetric: (id: number, body: Parameters<typeof updateMetric>[2]) => void;
  onDeleteMetric: (id: number) => void;
  onMatchMetric: (metricId: number) => void;
}

function SuccessCriteriaSection({
  goals,
  metrics,
  risks,
  memberMap,
  canEdit,
  onCreateGoal,
  onUpdateGoal,
  onDeleteGoal,
  onCreateMetric,
  onUpdateMetric,
  onDeleteMetric,
  onMatchMetric,
}: SuccessCriteriaSectionProps) {
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set(goals.map((g) => g.id)));
  const [addingGoal, setAddingGoal] = useState(false);
  const [editingGoal, setEditingGoal] = useState<number | null>(null);
  const [goalDraft, setGoalDraft] = useState<Partial<ProjectGoal>>({});
  const [addingKpiForGoal, setAddingKpiForGoal] = useState<number | null>(null);
  const [kpiDraft, setKpiDraft] = useState<KpiDraftState>({});
  const [editingKpi, setEditingKpi] = useState<number | null>(null);
  const [confirmDeleteGoal, setConfirmDeleteGoal] = useState<number | null>(null);
  const [confirmDeleteKpi, setConfirmDeleteKpi] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState<"updated_at" | "position">("updated_at");
  const [sortAsc, setSortAsc] = useState(false);

  const sortedGoals = useMemo(() => {
    const list = [...goals];
    list.sort((a, b) => {
      let cmp = 0;
      if (sortBy === "updated_at") {
        cmp = new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
      } else {
        cmp = (a.position || 0) - (b.position || 0);
      }
      return sortAsc ? cmp : -cmp;
    });
    return list;
  }, [goals, sortBy, sortAsc]);

  const getKpiTargetValue = (metric: ProjectMetric): number | null => {
    const target = metric.targets?.find((t) => t.active && t.status !== "archived");
    return target?.target_value != null ? Number(target.target_value) : null;
  };

  const toggle = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const saveGoal = () => {
    const body = {
      title: goalDraft.title || "Untitled criterion",
      description: goalDraft.description || null,
      category: goalDraft.category || null,
      priority: goalDraft.priority || "medium",
      owner_id: goalDraft.owner_id ?? null,
      status: goalDraft.status || "not_started",
      start_date: goalDraft.start_date || null,
      target_date: goalDraft.target_date || null,
      linked_metric_ids: [],
      linked_risk_ids: [],
    };
    if (editingGoal) {
      onUpdateGoal(editingGoal, { ...body, expected_version: goalDraft.version ?? 0 });
    } else {
      onCreateGoal(body);
    }
    setAddingGoal(false);
    setEditingGoal(null);
    setGoalDraft({});
  };

  const saveKpi = (goalId: number) => {
    const targetValue = kpiDraft.target_value ?? null;
    const body: MetricCreateRequest = {
      name: kpiDraft.name || "Untitled KPI",
      description: kpiDraft.description ?? null,
      business_definition: null,
      unit: kpiDraft.unit ?? null,
      format: kpiDraft.format ?? null,
      directionality: kpiDraft.directionality || "higher_is_better",
      aggregation: "sum",
      source_type: null,
      source_query_id: null,
      source_mapping: {},
      expression: null,
      success_criterion_id: goalId,
      owner_id: kpiDraft.owner_id ?? null,
      cadence: kpiDraft.cadence ?? null,
      targets: targetValue != null
        ? [{
            target_type: "single_value",
            target_value: targetValue,
            comparison_operator: kpiDraft.directionality === "lower_is_better" ? "<=" : ">=",
            status: "active",
          }]
        : [],
    };
    if (editingKpi) {
      onUpdateMetric(editingKpi, { ...body, expected_version: kpiDraft.version ?? 0 });
    } else {
      onCreateMetric(body);
    }
    setAddingKpiForGoal(null);
    setEditingKpi(null);
    setKpiDraft({});
  };

  return (
    <Card>
      <CardBody className="p-0">
        <div className="flex items-start justify-between border-b border-line-tertiary px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-primary">Success Criteria</h3>
            <p className="mt-0.5 text-xs text-ink-secondary">Define the outcomes that will demonstrate project success.</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-ink-secondary">Sort by</span>
            <select
              className="input h-8 text-xs"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as "updated_at" | "position")}
            >
              <option value="updated_at">Updated</option>
              <option value="position">Position</option>
            </select>
            <button
              onClick={() => setSortAsc((v) => !v)}
              className="rounded-md border border-line-secondary p-1 text-ink-secondary hover:bg-bg-secondary"
              title={sortAsc ? "Ascending" : "Descending"}
            >
              {sortAsc ? <IconChevronDown size={16} className="rotate-180" /> : <IconChevronDown size={16} />}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs font-medium uppercase tracking-wide text-ink-tertiary">
          <div className="col-span-4">Success Criterion</div>
          <div className="col-span-1">Owner</div>
          <div className="col-span-1">Status</div>
          <div className="col-span-2">Progress</div>
          <div className="col-span-2">Target Date</div>
          <div className="col-span-1">KPIs</div>
          <div className="col-span-1">Updated</div>
        </div>

        {(addingGoal || editingGoal !== null) && (
          <InlineGoalForm
            draft={goalDraft}
            setDraft={setGoalDraft}
            onSave={saveGoal}
            onCancel={() => { setAddingGoal(false); setEditingGoal(null); setGoalDraft({}); }}
            memberMap={memberMap}
            isEditing={editingGoal !== null}
          />
        )}

        {sortedGoals.map((goal) => {
          const children = metrics.filter((m) => m.success_criterion_id === goal.id);
          const progress = goalProgress(goal, metrics);
          const isOpen = expanded.has(goal.id);
          return (
            <div key={goal.id} className="border-t border-line-tertiary">
              <div className="group grid grid-cols-12 items-center gap-2 px-4 py-3 text-sm">
                <div className="col-span-4 flex items-center gap-2">
                  <button onClick={() => toggle(goal.id)} className="text-ink-tertiary hover:text-ink-primary">
                    {isOpen ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
                  </button>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-success-bg text-success">
                    <IconTarget size={16} />
                  </span>
                  {editingGoal === goal.id ? null : (
                    <>
                      <span className="font-medium text-ink-primary">{goal.title}</span>
                      {canEdit && (
                        <div className="ml-2 flex gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100">
                          <Button variant="ghost" size="icon" onClick={() => { setEditingGoal(goal.id); setGoalDraft({ ...goal }); }} title="Edit">
                            <IconPencil size={14} />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => setConfirmDeleteGoal(goal.id)} title="Delete">
                            <IconTrash size={14} />
                          </Button>
                        </div>
                      )}
                    </>
                  )}
                </div>
                <div className="col-span-1 flex items-center gap-1.5 text-ink-secondary">
                  {goal.owner_id ? (
                    <>
                      <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-bg-secondary text-[10px] font-semibold text-ink-secondary">
                        {initials(memberMap.get(goal.owner_id ?? -1)?.display_name || memberMap.get(goal.owner_id ?? -1)?.email)}
                      </span>
                      <span className="truncate">{displayName(memberMap, goal.owner_id)}</span>
                    </>
                  ) : (
                    "—"
                  )}
                </div>
                <div className="col-span-1">
                  <Badge tone={goalStatusTone(goal.status)} size="sm">{goal.status.replace("_", " ")}</Badge>
                </div>
                <div className="col-span-2">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-16 overflow-hidden rounded-full bg-bg-secondary">
                      <div className="h-full rounded-full bg-brand" style={{ width: `${progress}%` }} />
                    </div>
                    <span className="text-xs text-ink-secondary">{progress}%</span>
                  </div>
                </div>
                <div className="col-span-2 text-ink-secondary">{fmtDateShort(goal.target_date)}</div>
                <div className="col-span-1 text-ink-secondary">{children.length}</div>
                <div className="col-span-1 text-xs text-ink-tertiary">{fmtDate(goal.updated_at)}</div>
              </div>

              {isOpen && (
                <div className="bg-bg-secondary px-4 pb-4">
                  <div className="rounded-md border border-line-tertiary bg-bg-primary">
                    <div className="border-b border-line-tertiary px-3 py-2">
                      <div className="text-sm font-semibold text-ink-primary">KPIs</div>
                      <div className="text-xs text-ink-secondary">Key indicators used to evaluate this success criterion.</div>
                    </div>
                    <div className="grid grid-cols-12 gap-2 px-3 py-2 text-xs font-medium uppercase tracking-wide text-ink-tertiary">
                      <div className="col-span-3">KPI</div>
                      <div className="col-span-1">Current</div>
                      <div className="col-span-1">Target</div>
                      <div className="col-span-1">Trend</div>
                      <div className="col-span-2">Frequency</div>
                      <div className="col-span-2">Data Source</div>
                      <div className="col-span-1">Match Status</div>
                      <div className="col-span-1"></div>
                    </div>

                    {children.map((metric) => (
                      <KpiRow
                        key={metric.id}
                        metric={metric}
                        memberMap={memberMap}
                        canEdit={canEdit}
                        editing={editingKpi === metric.id}
                        draft={kpiDraft}
                        setDraft={setKpiDraft}
                        onEdit={() => { setEditingKpi(metric.id); setKpiDraft({ id: metric.id, name: metric.name, description: metric.description, latest_value: metric.latest_value, target_value: getKpiTargetValue(metric), directionality: metric.directionality, cadence: metric.cadence, unit: metric.unit, format: metric.format, owner_id: metric.owner_id, version: metric.version }); }}
                        onDelete={() => setConfirmDeleteKpi(metric.id)}
                        onMatch={() => onMatchMetric(metric.id)}
                        onSave={() => saveKpi(goal.id)}
                        onCancel={() => { setEditingKpi(null); setKpiDraft({}); }}
                      />
                    ))}

                    {children.length === 0 && <div className="px-3 py-3 text-sm text-ink-secondary">No KPIs yet.</div>}

                    {canEdit && addingKpiForGoal === goal.id && (
                      <div className="grid grid-cols-12 items-center gap-2 border-t border-line-tertiary px-3 py-2 text-sm">
                        <div className="col-span-3"><input className="input" placeholder="KPI name" value={kpiDraft.name ?? ""} onChange={(e) => setKpiDraft((d) => ({ ...d, name: e.target.value }))} /></div>
                        <div className="col-span-1"><input type="number" className="input" placeholder="Current" value={kpiDraft.latest_value ?? ""} onChange={(e) => setKpiDraft((d) => ({ ...d, latest_value: e.target.value ? Number(e.target.value) : null }))} /></div>
                        <div className="col-span-1"><input type="number" className="input" placeholder="Target" value={kpiDraft.target_value ?? ""} onChange={(e) => setKpiDraft((d) => ({ ...d, target_value: e.target.value ? Number(e.target.value) : null }))} /></div>
                        <div className="col-span-1"><select className="input" value={kpiDraft.directionality ?? "higher_is_better"} onChange={(e) => setKpiDraft((d) => ({ ...d, directionality: e.target.value }))}>{METRIC_DIRECTIONALITY.map((x) => (<option key={x.value} value={x.value}>{x.label}</option>))}</select></div>
                        <div className="col-span-2"><input className="input" placeholder="Frequency" value={kpiDraft.cadence ?? ""} onChange={(e) => setKpiDraft((d) => ({ ...d, cadence: e.target.value }))} /></div>
                        <div className="col-span-2"><input className="input" placeholder="Unit / format" value={kpiDraft.unit ?? ""} onChange={(e) => setKpiDraft((d) => ({ ...d, unit: e.target.value }))} /></div>
                        <div className="col-span-1"></div>
                        <div className="col-span-1 flex gap-1">
                          <Button variant="primary" size="sm" onClick={() => saveKpi(goal.id)}>Save</Button>
                          <Button variant="ghost" size="sm" onClick={() => setAddingKpiForGoal(null)}>Cancel</Button>
                        </div>
                      </div>
                    )}

                    {canEdit && addingKpiForGoal !== goal.id && (
                      <div className="border-t border-line-tertiary px-3 py-2">
                        <Button variant="brandSoft" size="sm" onClick={() => { setAddingKpiForGoal(goal.id); setKpiDraft({ directionality: "higher_is_better" }); }}>
                          <IconPlus size={14} /> Add KPI
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {canEdit && !addingGoal && (
          <button
            onClick={() => { setAddingGoal(true); setGoalDraft({ status: "not_started", priority: "medium" }); }}
            className="m-4 flex w-[calc(100%-2rem)] items-center justify-center gap-2 rounded-md border border-dashed border-line-secondary px-4 py-3 text-sm font-medium text-ink-secondary hover:bg-bg-secondary"
          >
            <IconPlus size={16} />
            Add success criterion
          </button>
        )}

        {goals.length === 0 && !addingGoal && <div className="px-4 py-6 text-sm text-ink-secondary">No success criteria defined yet.</div>}
      </CardBody>

      <ConfirmDialog
        open={confirmDeleteGoal !== null}
        title="Delete success criterion?"
        message={goalDeleteImpact(confirmDeleteGoal, goals, metrics, risks)}
        confirmLabel="Delete"
        onConfirm={() => { if (confirmDeleteGoal !== null) onDeleteGoal(confirmDeleteGoal); setConfirmDeleteGoal(null); }}
        onCancel={() => setConfirmDeleteGoal(null)}
      />
      <ConfirmDialog
        open={confirmDeleteKpi !== null}
        title="Delete KPI?"
        message="This will archive the KPI. It can be restored later."
        confirmLabel="Delete"
        onConfirm={() => { if (confirmDeleteKpi !== null) onDeleteMetric(confirmDeleteKpi); setConfirmDeleteKpi(null); }}
        onCancel={() => setConfirmDeleteKpi(null)}
      />
    </Card>
  );
}

function InlineGoalForm({
  draft,
  setDraft,
  onSave,
  onCancel,
  memberMap,
  isEditing,
}: {
  draft: Partial<ProjectGoal>;
  setDraft: (d: Partial<ProjectGoal> | ((prev: Partial<ProjectGoal>) => Partial<ProjectGoal>)) => void;
  onSave: () => void;
  onCancel: () => void;
  memberMap: Map<number, ProjectMember>;
  isEditing: boolean;
}) {
  const members = Array.from(memberMap.values());
  return (
    <div className="grid grid-cols-12 items-center gap-2 border-t border-line-tertiary px-4 py-3 text-sm">
      <div className="col-span-4">
        <input className="input" placeholder="Success criterion title" value={draft.title ?? ""} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} />
      </div>
      <div className="col-span-1">
        <select className="input" value={draft.owner_id ?? ""} onChange={(e) => setDraft((d) => ({ ...d, owner_id: e.target.value ? Number(e.target.value) : null }))}>
          <option value="">—</option>
          {members.map((m) => (<option key={m.user_id} value={m.user_id}>{m.display_name || m.email}</option>))}
        </select>
      </div>
      <div className="col-span-1">
        <select className="input" value={draft.status ?? "not_started"} onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}>
          {GOAL_STATUSES.map((s) => (<option key={s} value={s}>{s.replace("_", " ")}</option>))}
        </select>
      </div>
      <div className="col-span-2"></div>
      <div className="col-span-2">
        <input type="date" className="input" value={draft.target_date?.slice(0, 10) ?? ""} onChange={(e) => setDraft((d) => ({ ...d, target_date: e.target.value || null }))} />
      </div>
      <div className="col-span-1"></div>
      <div className="col-span-1 flex gap-1">
        <Button variant="primary" size="sm" onClick={onSave}>{isEditing ? "Save" : "Add"}</Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

function KpiRow({
  metric,
  memberMap,
  canEdit,
  editing,
  draft,
  setDraft,
  onEdit,
  onDelete,
  onMatch,
  onSave,
  onCancel,
}: {
  metric: ProjectMetric;
  memberMap: Map<number, ProjectMember>;
  canEdit: boolean;
  editing: boolean;
  draft: KpiDraftState;
  setDraft: (d: KpiDraftState | ((prev: KpiDraftState) => KpiDraftState)) => void;
  onEdit: () => void;
  onDelete: () => void;
  onMatch: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const target = metric.targets?.find((t) => t.active && t.status !== "archived");
  const trendMeta = metricTrendMeta(metric);
  const currentValue = metric.latest_value != null ? Number(metric.latest_value) : null;
  const targetValue = target?.target_value != null ? Number(target.target_value) : null;

  if (editing) {
    return (
      <div className="grid grid-cols-12 items-center gap-2 border-t border-line-tertiary px-3 py-2 text-sm">
        <div className="col-span-3"><input className="input" value={draft.name ?? ""} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} /></div>
        <div className="col-span-1"><input type="number" className="input" value={draft.latest_value ?? ""} onChange={(e) => setDraft((d) => ({ ...d, latest_value: e.target.value ? Number(e.target.value) : null }))} /></div>
        <div className="col-span-1"><input type="number" className="input" value={draft.target_value ?? ""} onChange={(e) => setDraft((d) => ({ ...d, target_value: e.target.value ? Number(e.target.value) : null }))} /></div>
        <div className="col-span-1"><select className="input" value={draft.directionality ?? "higher_is_better"} onChange={(e) => setDraft((d) => ({ ...d, directionality: e.target.value }))}>{METRIC_DIRECTIONALITY.map((x) => (<option key={x.value} value={x.value}>{x.label}</option>))}</select></div>
        <div className="col-span-2"><input className="input" value={draft.cadence ?? ""} onChange={(e) => setDraft((d) => ({ ...d, cadence: e.target.value }))} /></div>
        <div className="col-span-2"><input className="input" value={draft.unit ?? ""} onChange={(e) => setDraft((d) => ({ ...d, unit: e.target.value }))} /></div>
        <div className="col-span-1"></div>
        <div className="col-span-1 flex gap-1">
          <Button variant="primary" size="sm" onClick={onSave}>Save</Button>
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
        </div>
      </div>
    );
  }

  const mapping = metric.source_mapping as Record<string, unknown> | null;
  const dataSource = metric.source_match_status === "matched" && mapping && "matched_query_name" in mapping
    ? String(mapping.matched_query_name)
    : metric.source_type || "—";

  return (
    <div className="grid grid-cols-12 items-center gap-2 border-t border-line-tertiary px-3 py-2 text-sm">
      <div className="col-span-3 flex items-center gap-2 font-medium text-ink-primary">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-bg-secondary text-ink-secondary">
          {metricIcon(metric.id)}
        </span>
        {metric.name}
      </div>
      <div className="col-span-1 text-ink-secondary">{fmtNumber(currentValue, metric.format, metric.unit)}</div>
      <div className="col-span-1 text-ink-secondary">{formatTarget(targetValue, metric.directionality, metric.format, metric.unit)}</div>
      <div className="col-span-1">
        <Badge tone={trendMeta.tone} size="sm" className="gap-1">
          {trendMeta.direction === "up" ? <IconTrendingUp size={14} /> : trendMeta.direction === "down" ? <IconTrendingDown size={14} /> : <IconMinus size={14} />}
          {trendMeta.label}
        </Badge>
      </div>
      <div className="col-span-2 text-ink-secondary">{metric.cadence || "—"}</div>
      <div className="col-span-2 text-ink-secondary">{dataSource}</div>
      <div className="col-span-1">
        <Badge tone={matchStatusTone(metric.source_match_status)} size="sm">{metric.source_match_status || "Unmatched"}</Badge>
      </div>
      <div className="col-span-1 flex gap-1">
        {!metric.source_match_status || metric.source_match_status === "no_match" ? (
          <Button variant="brandSoft" size="sm" onClick={onMatch}>Match</Button>
        ) : null}
        {canEdit && (
          <>
            <Button variant="ghost" size="icon" onClick={onEdit} title="Edit"><IconPencil size={14} /></Button>
            <Button variant="ghost" size="icon" onClick={onDelete} title="Delete"><IconTrash size={14} /></Button>
          </>
        )}
      </div>
    </div>
  );
}

interface RisksSectionProps {
  risks: ProjectRisk[];
  memberMap: Map<number, ProjectMember>;
  canEdit: boolean;
  onCreateRisk: (body: Parameters<typeof createRisk>[1]) => void;
  onUpdateRisk: (id: number, body: Parameters<typeof updateRisk>[2]) => void;
  onDeleteRisk: (id: number) => void;
}

function RisksSection({ risks, memberMap, canEdit, onCreateRisk, onUpdateRisk, onDeleteRisk }: RisksSectionProps) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<Partial<ProjectRisk>>({});
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const members = Array.from(memberMap.values());

  const saveRisk = () => {
    const body = {
      title: draft.title || "Untitled risk",
      description: draft.description || null,
      category: draft.category || null,
      likelihood: draft.likelihood || "possible",
      impact: draft.impact || "moderate",
      owner_id: draft.owner_id ?? null,
      mitigation: draft.mitigation || null,
      contingency: draft.contingency || null,
      status: draft.status || "open",
      review_date: draft.review_date || null,
      source_reference: draft.source_reference || null,
      linked_goal_ids: [],
      linked_metric_ids: [],
    };
    if (editing) {
      onUpdateRisk(editing, { ...body, expected_version: draft.version ?? 0 });
    } else {
      onCreateRisk(body);
    }
    setAdding(false);
    setEditing(null);
    setDraft({});
  };

  const startAdd = () => {
    setAdding(true);
    setDraft({ likelihood: "possible", impact: "moderate", status: "open" });
  };

  return (
    <Card>
      <CardBody className="p-0">
        <div className="flex items-start justify-between border-b border-line-tertiary px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-primary">Project Risks</h3>
            <p className="mt-0.5 text-xs text-ink-secondary">Track conditions that could affect the overall project, independent of a specific success criterion.</p>
          </div>
          {canEdit && !adding && !editing && (
            <Button variant="primary" size="sm" onClick={startAdd}>
              <IconPlus size={14} /> Add project risk
            </Button>
          )}
        </div>

        <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs font-medium uppercase tracking-wide text-ink-tertiary">
          <div className="col-span-2">Risk</div>
          <div className="col-span-1">Owner</div>
          <div className="col-span-1">Likelihood</div>
          <div className="col-span-1">Impact</div>
          <div className="col-span-1">Rating</div>
          <div className="col-span-1">Status</div>
          <div className="col-span-3">Mitigation</div>
          <div className="col-span-1">Updated</div>
          <div className="col-span-1"></div>
        </div>

        {(adding || editing !== null) && (
          <InlineRiskForm
            draft={draft}
            setDraft={setDraft}
            members={members}
            onSave={saveRisk}
            onCancel={() => { setAdding(false); setEditing(null); setDraft({}); }}
          />
        )}

        {risks.map((risk) => (
          <RiskRow
            key={risk.id}
            risk={risk}
            memberMap={memberMap}
            canEdit={canEdit}
            editing={editing === risk.id}
            draft={draft}
            setDraft={setDraft}
            onEdit={() => { setEditing(risk.id); setDraft({ ...risk }); }}
            onDelete={() => setConfirmDelete(risk.id)}
            onSave={saveRisk}
            onCancel={() => { setEditing(null); setDraft({}); }}
          />
        ))}

        {risks.length === 0 && !adding && <div className="px-4 py-6 text-sm text-ink-secondary">No project risks defined yet.</div>}

        {canEdit && !adding && !editing && risks.length > 0 && (
          <button
            onClick={startAdd}
            className="m-4 flex w-[calc(100%-2rem)] items-center justify-center gap-2 rounded-md border border-dashed border-line-secondary px-4 py-3 text-sm font-medium text-ink-secondary hover:bg-bg-secondary"
          >
            <IconPlus size={16} />
            Add another risk
          </button>
        )}
      </CardBody>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="Delete risk?"
        message="This will archive the risk. It can be restored later."
        confirmLabel="Delete"
        onConfirm={() => { if (confirmDelete !== null) onDeleteRisk(confirmDelete); setConfirmDelete(null); }}
        onCancel={() => setConfirmDelete(null)}
      />
    </Card>
  );
}

function InlineRiskForm({
  draft,
  setDraft,
  members,
  onSave,
  onCancel,
}: {
  draft: Partial<ProjectRisk>;
  setDraft: (d: Partial<ProjectRisk> | ((prev: Partial<ProjectRisk>) => Partial<ProjectRisk>)) => void;
  members: ProjectMember[];
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="grid grid-cols-12 items-center gap-2 border-t border-line-tertiary px-4 py-3 text-sm">
      <div className="col-span-2"><input className="input" placeholder="Risk title" value={draft.title ?? ""} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} /></div>
      <div className="col-span-1">
        <select className="input" value={draft.owner_id ?? ""} onChange={(e) => setDraft((d) => ({ ...d, owner_id: e.target.value ? Number(e.target.value) : null }))}>
          <option value="">—</option>
          {members.map((m) => (<option key={m.user_id} value={m.user_id}>{m.display_name || m.email}</option>))}
        </select>
      </div>
      <div className="col-span-1">
        <select className="input" value={draft.likelihood ?? "possible"} onChange={(e) => setDraft((d) => ({ ...d, likelihood: e.target.value }))}>
          {RISK_LIKELIHOOD.map((x) => (<option key={x} value={x}>{x}</option>))}
        </select>
      </div>
      <div className="col-span-1">
        <select className="input" value={draft.impact ?? "moderate"} onChange={(e) => setDraft((d) => ({ ...d, impact: e.target.value }))}>
          {RISK_IMPACT.map((x) => (<option key={x} value={x}>{x}</option>))}
        </select>
      </div>
      <div className="col-span-1 text-ink-secondary" title="Calculated on save">—</div>
      <div className="col-span-1">
        <select className="input" value={draft.status ?? "open"} onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}>
          {RISK_STATUSES.map((x) => (<option key={x} value={x}>{x}</option>))}
        </select>
      </div>
      <div className="col-span-3"><input className="input" placeholder="Mitigation" value={draft.mitigation ?? ""} onChange={(e) => setDraft((d) => ({ ...d, mitigation: e.target.value }))} /></div>
      <div className="col-span-1"></div>
      <div className="col-span-1 flex gap-1">
        <Button variant="primary" size="sm" onClick={onSave}>Save</Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

function RiskRow({
  risk,
  memberMap,
  canEdit,
  editing,
  draft,
  setDraft,
  onEdit,
  onDelete,
  onSave,
  onCancel,
}: {
  risk: ProjectRisk;
  memberMap: Map<number, ProjectMember>;
  canEdit: boolean;
  editing: boolean;
  draft: Partial<ProjectRisk>;
  setDraft: (d: Partial<ProjectRisk> | ((prev: Partial<ProjectRisk>) => Partial<ProjectRisk>)) => void;
  onEdit: () => void;
  onDelete: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const members = Array.from(memberMap.values());
  if (editing) {
    return (
      <InlineRiskForm
        draft={draft}
        setDraft={setDraft}
        members={members}
        onSave={onSave}
        onCancel={onCancel}
      />
    );
  }

  const ownerName = displayName(memberMap, risk.owner_id);
  const ownerInitials = initials(memberMap.get(risk.owner_id ?? -1)?.display_name || memberMap.get(risk.owner_id ?? -1)?.email);

  return (
    <div className="grid grid-cols-12 items-center gap-2 border-t border-line-tertiary px-4 py-3 text-sm">
      <div className="col-span-2 font-medium text-ink-primary">{risk.title}</div>
      <div className="col-span-1 flex items-center gap-1.5 text-ink-secondary">
        {risk.owner_id ? (
          <>
            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-bg-secondary text-[10px] font-semibold text-ink-secondary">
              {ownerInitials}
            </span>
            <span className="truncate">{ownerName}</span>
          </>
        ) : (
          "—"
        )}
      </div>
      <div className="col-span-1"><Badge tone={likelihoodTone(risk.likelihood)} size="sm">{risk.likelihood || "—"}</Badge></div>
      <div className="col-span-1"><Badge tone={impactTone(risk.impact)} size="sm">{risk.impact || "—"}</Badge></div>
      <div className="col-span-1"><Badge tone={riskSeverityTone(risk.severity)} size="sm">{risk.severity || "—"}</Badge></div>
      <div className="col-span-1"><Badge tone={riskStatusTone(risk.status)} size="sm">{risk.status}</Badge></div>
      <div className="col-span-3 truncate text-ink-secondary" title={risk.mitigation || undefined}>{risk.mitigation || "—"}</div>
      <div className="col-span-1 text-xs text-ink-tertiary">{fmtDate(risk.updated_at)}</div>
      <div className="col-span-1 flex gap-1">
        {canEdit && (
          <>
            <Button variant="ghost" size="icon" onClick={onEdit} title="Edit"><IconPencil size={14} /></Button>
            <Button variant="ghost" size="icon" onClick={onDelete} title="Delete"><IconTrash size={14} /></Button>
          </>
        )}
      </div>
    </div>
  );
}
