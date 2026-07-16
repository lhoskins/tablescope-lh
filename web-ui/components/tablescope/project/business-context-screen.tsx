"use client";

import { useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  IconPlus,
  IconTrash,
  IconPencil,
  IconCheck,
  IconX,
  IconSettings,
  IconTarget,
  IconFlag,
  IconTrendingUp,
  IconRobot,
  IconHistory,
  IconBulb,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { StatTile } from "@/components/ui/stat-tile";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { cn } from "@/lib/cn";
import {
  getProjectContext,
  updateProjectSettings,
  createGoal,
  updateGoal,
  deleteGoal,
  reorderGoals,
  createMetric,
  updateMetric,
  deleteMetric,
  reorderMetrics,
  createRisk,
  updateRisk,
  deleteRisk,
  reorderRisks,
  createTarget,
  updateTarget,
  deleteTarget,
  listProjectContextAudit,
  type ProjectContext,
  type ProjectBusinessContext,
  type ProjectGoal,
  type ProjectMetric,
  type ProjectRisk,
  type ProjectMetricTarget,
  type ProjectContextAuditEvent,
} from "@/lib/api/project-context";

const TABS = [
  { key: "settings", label: "General Settings", icon: IconSettings },
  { key: "goals", label: "Goals", icon: IconTrendingUp },
  { key: "metrics", label: "Metrics & Targets", icon: IconTarget },
  { key: "risks", label: "Risks", icon: IconFlag },
  { key: "ai", label: "AI Context", icon: IconRobot },
  { key: "audit", label: "Audit History", icon: IconHistory },
];

const PRIORITIES = ["low", "medium", "high", "critical"];
const GOAL_STATUSES = ["not_started", "in_progress", "at_risk", "achieved", "cancelled"];
const RISK_LIKELIHOOD = ["rare", "unlikely", "possible", "likely", "almost_certain"];
const RISK_IMPACT = ["insignificant", "minor", "moderate", "major", "catastrophic"];
const RISK_SEVERITY = ["low", "medium", "high", "critical"];
const RISK_STATUSES = ["open", "mitigating", "monitoring", "closed"];
const TARGET_TYPES = ["single_value", "range", "threshold", "milestone"];
const COMPARISON_OPS = [">=", ">", "<=", "<", "==", "!="];
const METRIC_DIRECTIONALITY = ["higher_is_better", "lower_is_better", "neutral"];
const METRIC_AGGREGATIONS = ["sum", "average", "count", "min", "max", "last", "custom"];

function fmtDate(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  return Number.isNaN(d.getTime())
    ? ts
    : d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
}

export function BusinessContextScreen({ projectId }: { projectId: string }) {
  const [activeTab, setActiveTab] = useState("settings");
  const queryClient = useQueryClient();
  const { toasts, push, dismiss } = useToasts();

  const contextQueryKey = ["project-context", projectId];
  const { data, isLoading, refetch } = useQuery<ProjectContext>({
    queryKey: contextQueryKey,
    queryFn: () => getProjectContext(projectId),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: contextQueryKey });
    void refetch();
  };

  const auditQueryKey = ["project-context-audit", projectId];
  const { data: auditData } = useQuery<{
    items: ProjectContextAuditEvent[];
    total: number;
  }>({
    queryKey: auditQueryKey,
    queryFn: () => listProjectContextAudit(projectId, { limit: 100 }),
    enabled: activeTab === "audit",
  });

  const onError = (e: unknown) => {
    push(
      e instanceof Error ? e.message : "An unexpected error occurred",
      "error",
    );
  };

  const settingsMutation = useMutation({
    mutationFn: (body: Parameters<typeof updateProjectSettings>[1]) =>
      updateProjectSettings(projectId, body),
    onSuccess: () => {
      push("Settings saved", "success");
      refresh();
    },
    onError,
  });

  const goalCreate = useMutation({
    mutationFn: createGoal.bind(null, projectId),
    onSuccess: () => {
      push("Goal created", "success");
      refresh();
    },
    onError,
  });
  const goalUpdate = useMutation({
    mutationFn: (args: { goalId: number; body: Parameters<typeof updateGoal>[2] }) =>
      updateGoal(projectId, args.goalId, args.body),
    onSuccess: () => {
      push("Goal updated", "success");
      refresh();
    },
    onError,
  });
  const goalDelete = useMutation({
    mutationFn: deleteGoal.bind(null, projectId),
    onSuccess: () => {
      push("Goal deleted", "success");
      refresh();
    },
    onError,
  });

  const metricCreate = useMutation({
    mutationFn: createMetric.bind(null, projectId),
    onSuccess: () => {
      push("Metric created", "success");
      refresh();
    },
    onError,
  });
  const metricUpdate = useMutation({
    mutationFn: (args: { metricId: number; body: Parameters<typeof updateMetric>[2] }) =>
      updateMetric(projectId, args.metricId, args.body),
    onSuccess: () => {
      push("Metric updated", "success");
      refresh();
    },
    onError,
  });
  const metricDelete = useMutation({
    mutationFn: deleteMetric.bind(null, projectId),
    onSuccess: () => {
      push("Metric deleted", "success");
      refresh();
    },
    onError,
  });

  const riskCreate = useMutation({
    mutationFn: createRisk.bind(null, projectId),
    onSuccess: () => {
      push("Risk created", "success");
      refresh();
    },
    onError,
  });
  const riskUpdate = useMutation({
    mutationFn: (args: { riskId: number; body: Parameters<typeof updateRisk>[2] }) =>
      updateRisk(projectId, args.riskId, args.body),
    onSuccess: () => {
      push("Risk updated", "success");
      refresh();
    },
    onError,
  });
  const riskDelete = useMutation({
    mutationFn: deleteRisk.bind(null, projectId),
    onSuccess: () => {
      push("Risk deleted", "success");
      refresh();
    },
    onError,
  });

  const targetCreate = useMutation({
    mutationFn: (args: { metricId: number; body: Parameters<typeof createTarget>[2] }) =>
      createTarget(projectId, args.metricId, args.body),
    onSuccess: () => {
      push("Target created", "success");
      refresh();
    },
    onError,
  });
  const targetUpdate = useMutation({
    mutationFn: (args: {
      metricId: number;
      targetId: number;
      body: Parameters<typeof updateTarget>[3];
    }) => updateTarget(projectId, args.metricId, args.targetId, args.body),
    onSuccess: () => {
      push("Target updated", "success");
      refresh();
    },
    onError,
  });
  const targetDelete = useMutation({
    mutationFn: (args: { metricId: number; targetId: number }) =>
      deleteTarget(projectId, args.metricId, args.targetId),
    onSuccess: () => {
      push("Target deleted", "success");
      refresh();
    },
    onError,
  });

  const canEdit = data?.permissions.can_edit ?? false;
  const version = data?.version ?? 0;

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-business-context"
      breadcrumbLabel="Business Context"
      actions={
        <Button variant="secondary" onClick={() => void refetch()}>
          <IconBulb size={14} />
          Refresh
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Goals" value={data?.goals?.length ?? 0} />
          <StatTile label="Metrics" value={data?.metrics?.length ?? 0} />
          <StatTile label="Risks" value={data?.risks?.length ?? 0} />
          <StatTile
            label="AI Context"
            value={data?.settings?.ai_context_enabled ? "Enabled" : "Disabled"}
            hint={data?.settings?.ai_context_enabled ? "Injected into insights" : "Not used"}
          />
        </div>

        <div className="flex flex-wrap gap-2 border-b border-line-tertiary">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  "flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-medium transition-colors",
                  activeTab === tab.key
                    ? "border-brand text-brand-700"
                    : "border-transparent text-ink-secondary hover:text-ink-primary",
                )}
              >
                <Icon size={16} />
                {tab.label}
              </button>
            );
          })}
        </div>

        {isLoading && (
          <Card>
            <CardBody>
              <div className="text-sm text-ink-secondary">Loading business context…</div>
            </CardBody>
          </Card>
        )}

        {!isLoading && activeTab === "settings" && (
          <SettingsPanel
            settings={data?.settings}
            version={version}
            canEdit={canEdit}
            onSave={settingsMutation.mutate}
            isSaving={settingsMutation.isPending}
          />
        )}
        {!isLoading && activeTab === "goals" && (
          <GoalsPanel
            goals={data?.goals ?? []}
            canEdit={canEdit}
            onCreate={(body) => goalCreate.mutate(body)}
            onUpdate={(id, body) => goalUpdate.mutate({ goalId: id, body })}
            onDelete={(id) => goalDelete.mutate(id)}
          />
        )}
        {!isLoading && activeTab === "metrics" && (
          <MetricsPanel
            metrics={data?.metrics ?? []}
            canEdit={canEdit}
            onCreate={(body) => metricCreate.mutate(body)}
            onUpdate={(id, body) => metricUpdate.mutate({ metricId: id, body })}
            onDelete={(id) => metricDelete.mutate(id)}
            onCreateTarget={(metricId, body) => targetCreate.mutate({ metricId, body })}
            onUpdateTarget={(metricId, targetId, body) =>
              targetUpdate.mutate({ metricId, targetId, body })
            }
            onDeleteTarget={(metricId, targetId) => targetDelete.mutate({ metricId, targetId })}
          />
        )}
        {!isLoading && activeTab === "risks" && (
          <RisksPanel
            risks={data?.risks ?? []}
            canEdit={canEdit}
            onCreate={(body) => riskCreate.mutate(body)}
            onUpdate={(id, body) => riskUpdate.mutate({ riskId: id, body })}
            onDelete={(id) => riskDelete.mutate(id)}
          />
        )}
        {!isLoading && activeTab === "ai" && (
          <AiContextPanel settings={data?.settings} canEdit={canEdit} onSave={settingsMutation.mutate} />
        )}
        {!isLoading && activeTab === "audit" && (
          <AuditPanel events={auditData?.items ?? []} total={auditData?.total ?? 0} />
        )}
      </div>
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ProjectShell>
  );
}

function SettingsPanel({
  settings,
  version,
  canEdit,
  onSave,
  isSaving,
}: {
  settings: ProjectBusinessContext | null | undefined;
  version: number;
  canEdit: boolean;
  onSave: (body: Parameters<typeof updateProjectSettings>[1]) => void;
  isSaving: boolean;
}) {
  const [form, setForm] = useState<Partial<ProjectBusinessContext>>(() =>
    settings ? { ...settings } : {},
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({ ...form, expected_version: version });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>General Settings</CardTitle>
      </CardHeader>
      <CardBody>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Business Owner ID">
              <input
                type="number"
                className="input"
                value={form.business_owner_id ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    business_owner_id: e.target.value ? Number(e.target.value) : null,
                  }))
                }
                disabled={!canEdit}
              />
            </Field>
            <Field label="Business Function">
              <input
                type="text"
                className="input"
                value={form.business_function ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, business_function: e.target.value }))}
                disabled={!canEdit}
              />
            </Field>
            <Field label="Industry">
              <input
                type="text"
                className="input"
                value={form.industry ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, industry: e.target.value }))}
                disabled={!canEdit}
              />
            </Field>
            <Field label="Reporting Cadence">
              <input
                type="text"
                className="input"
                value={form.reporting_cadence ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, reporting_cadence: e.target.value }))}
                disabled={!canEdit}
              />
            </Field>
            <Field label="Default Timezone">
              <input
                type="text"
                className="input"
                value={form.timezone ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}
                disabled={!canEdit}
              />
            </Field>
            <Field label="Default Currency">
              <input
                type="text"
                className="input"
                value={form.currency ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))}
                disabled={!canEdit}
              />
            </Field>
            <Field label="Fiscal Year Start Month (1-12)">
              <input
                type="number"
                min={1}
                max={12}
                className="input"
                value={form.fiscal_year_start_month ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    fiscal_year_start_month: e.target.value ? Number(e.target.value) : null,
                  }))
                }
                disabled={!canEdit}
              />
            </Field>
          </div>
          <Field label="Purpose / Business Context">
            <textarea
              className="input min-h-[80px]"
              value={form.purpose ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, purpose: e.target.value }))}
              disabled={!canEdit}
            />
          </Field>
          {canEdit && (
            <div className="flex justify-end">
              <Button type="submit" variant="primary" disabled={isSaving}>
                {isSaving ? "Saving…" : "Save Settings"}
              </Button>
            </div>
          )}
        </form>
      </CardBody>
    </Card>
  );
}

function AiContextPanel({
  settings,
  canEdit,
  onSave,
}: {
  settings: ProjectBusinessContext | null | undefined;
  canEdit: boolean;
  onSave: (body: Parameters<typeof updateProjectSettings>[1]) => void;
}) {
  const [enabled, setEnabled] = useState(settings?.ai_context_enabled ?? false);
  const [instructions, setInstructions] = useState(settings?.ai_instructions ?? "");
  const [notes, setNotes] = useState(settings?.interpretation_notes ?? "");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      ai_context_enabled: enabled,
      ai_instructions: instructions || null,
      interpretation_notes: notes || null,
      expected_version: settings?.version ?? 0,
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Context Injection</CardTitle>
      </CardHeader>
      <CardBody>
        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              disabled={!canEdit}
            />
            Enable AI context injection for Business Insight, Project Insight, and Conversational Analytics
          </label>
          <Field label="Bounded AI Instructions">
            <textarea
              className="input min-h-[100px]"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              disabled={!canEdit}
              placeholder="Project-specific guidance for the AI, e.g. always compare totals to prior month."
            />
          </Field>
          <Field label="Interpretation Notes">
            <textarea
              className="input min-h-[80px]"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={!canEdit}
              placeholder="Notes on how metrics, targets, and risks should be interpreted."
            />
          </Field>
          {canEdit && (
            <div className="flex justify-end">
              <Button type="submit" variant="primary">
                Save AI Context
              </Button>
            </div>
          )}
        </form>
      </CardBody>
    </Card>
  );
}

interface GoalDraft extends Partial<ProjectGoal> {
  linked_metric_ids?: number[];
  linked_risk_ids?: number[];
}

function GoalsPanel({
  goals,
  canEdit,
  onCreate,
  onUpdate,
  onDelete,
}: {
  goals: ProjectGoal[];
  canEdit: boolean;
  onCreate: (body: Parameters<typeof createGoal>[1]) => void;
  onUpdate: (id: number, body: Parameters<typeof updateGoal>[2]) => void;
  onDelete: (id: number) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<GoalDraft>({});
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const startEdit = (goal: ProjectGoal) => {
    setEditing(goal.id);
    setDraft({ ...goal });
  };

  const startAdd = () => {
    setAdding(true);
    setDraft({ priority: "medium", status: "not_started", linked_metric_ids: [], linked_risk_ids: [] });
  };

  const submit = () => {
    const body = {
      title: draft.title || "Untitled goal",
      description: draft.description || null,
      category: draft.category || null,
      priority: draft.priority || "medium",
      owner_id: draft.owner_id ?? null,
      status: draft.status || "not_started",
      start_date: draft.start_date || null,
      target_date: draft.target_date || null,
      linked_metric_ids: draft.linked_metric_ids || [],
      linked_risk_ids: draft.linked_risk_ids || [],
    };
    if (editing) {
      onUpdate(editing, { ...body, expected_version: draft.version ?? 0 });
    } else {
      onCreate(body);
    }
    setAdding(false);
    setEditing(null);
    setDraft({});
  };

  const cancel = () => {
    setAdding(false);
    setEditing(null);
    setDraft({});
  };

  return (
    <div className="space-y-3">
      {canEdit && !adding && !editing && (
        <div className="flex justify-end">
          <Button variant="primary" size="sm" onClick={startAdd}>
            <IconPlus size={14} />
            Add goal
          </Button>
        </div>
      )}
      {(adding || editing !== null) && (
        <Card>
          <CardHeader>
            <CardTitle>{editing ? "Edit goal" : "New goal"}</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Title">
                <input
                  className="input"
                  value={draft.title ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
                />
              </Field>
              <Field label="Category">
                <input
                  className="input"
                  value={draft.category ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))}
                />
              </Field>
              <Field label="Priority">
                <select
                  className="input"
                  value={draft.priority ?? "medium"}
                  onChange={(e) => setDraft((d) => ({ ...d, priority: e.target.value }))}
                >
                  {PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Status">
                <select
                  className="input"
                  value={draft.status ?? "not_started"}
                  onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}
                >
                  {GOAL_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Owner ID">
                <input
                  type="number"
                  className="input"
                  value={draft.owner_id ?? ""}
                  onChange={(e) =>
                    setDraft((d) => ({
                      ...d,
                      owner_id: e.target.value ? Number(e.target.value) : null,
                    }))
                  }
                />
              </Field>
              <Field label="Start date">
                <input
                  type="date"
                  className="input"
                  value={draft.start_date?.slice(0, 10) ?? ""}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, start_date: e.target.value || null }))
                  }
                />
              </Field>
              <Field label="Target date">
                <input
                  type="date"
                  className="input"
                  value={draft.target_date?.slice(0, 10) ?? ""}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, target_date: e.target.value || null }))
                  }
                />
              </Field>
            </div>
            <Field label="Description" className="mt-3">
              <textarea
                className="input min-h-[80px]"
                value={draft.description ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
              />
            </Field>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={cancel}>
                <IconX size={14} />
                Cancel
              </Button>
              <Button variant="primary" size="sm" onClick={submit}>
                <IconCheck size={14} />
                Save
              </Button>
            </div>
          </CardBody>
        </Card>
      )}
      <div className="space-y-2">
        {goals.map((goal) => (
          <Card key={goal.id} className="p-0">
            <CardBody className="p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h4 className="font-medium text-ink-primary">{goal.title}</h4>
                    <Badge tone={goal.priority === "high" || goal.priority === "critical" ? "danger" : "neutral"}>
                      {goal.priority}
                    </Badge>
                    <Badge tone="outline">{goal.status}</Badge>
                  </div>
                  {goal.description && (
                    <p className="mt-1 text-sm text-ink-secondary">{goal.description}</p>
                  )}
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink-tertiary">
                    <span>Target: {goal.target_date ? fmtDate(goal.target_date) : "—"}</span>
                    <span>Version: {goal.version}</span>
                  </div>
                </div>
                {canEdit && (
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" onClick={() => startEdit(goal)} title="Edit">
                      <IconPencil size={14} />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setConfirmDelete(goal.id)}
                      title="Delete"
                    >
                      <IconTrash size={14} />
                    </Button>
                  </div>
                )}
              </div>
            </CardBody>
          </Card>
        ))}
        {goals.length === 0 && (
          <div className="text-sm text-ink-secondary">No goals defined yet.</div>
        )}
      </div>
      <ConfirmDialog
        open={confirmDelete !== null}
        title="Delete goal?"
        message="This will archive the goal. It can be restored later."
        confirmLabel="Delete"
        onConfirm={() => {
          if (confirmDelete !== null) onDelete(confirmDelete);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

interface RiskDraft extends Partial<ProjectRisk> {
  linked_goal_ids?: number[];
  linked_metric_ids?: number[];
}

function RisksPanel({
  risks,
  canEdit,
  onCreate,
  onUpdate,
  onDelete,
}: {
  risks: ProjectRisk[];
  canEdit: boolean;
  onCreate: (body: Parameters<typeof createRisk>[1]) => void;
  onUpdate: (id: number, body: Parameters<typeof updateRisk>[2]) => void;
  onDelete: (id: number) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<RiskDraft>({});
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const startEdit = (risk: ProjectRisk) => {
    setEditing(risk.id);
    setDraft({ ...risk });
  };

  const startAdd = () => {
    setAdding(true);
    setDraft({
      likelihood: "possible",
      impact: "moderate",
      severity: "medium",
      status: "open",
      linked_goal_ids: [],
      linked_metric_ids: [],
    });
  };

  const submit = () => {
    const body = {
      title: draft.title || "Untitled risk",
      description: draft.description || null,
      category: draft.category || null,
      likelihood: draft.likelihood || "possible",
      impact: draft.impact || "moderate",
      severity: draft.severity || "medium",
      owner_id: draft.owner_id ?? null,
      mitigation: draft.mitigation || null,
      contingency: draft.contingency || null,
      status: draft.status || "open",
      review_date: draft.review_date || null,
      source_reference: draft.source_reference || null,
      linked_goal_ids: draft.linked_goal_ids || [],
      linked_metric_ids: draft.linked_metric_ids || [],
    };
    if (editing) {
      onUpdate(editing, { ...body, expected_version: draft.version ?? 0 });
    } else {
      onCreate(body);
    }
    setAdding(false);
    setEditing(null);
    setDraft({});
  };

  const cancel = () => {
    setAdding(false);
    setEditing(null);
    setDraft({});
  };

  return (
    <div className="space-y-3">
      {canEdit && !adding && !editing && (
        <div className="flex justify-end">
          <Button variant="primary" size="sm" onClick={startAdd}>
            <IconPlus size={14} />
            Add risk
          </Button>
        </div>
      )}
      {(adding || editing !== null) && (
        <Card>
          <CardHeader>
            <CardTitle>{editing ? "Edit risk" : "New risk"}</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Title">
                <input
                  className="input"
                  value={draft.title ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
                />
              </Field>
              <Field label="Category">
                <input
                  className="input"
                  value={draft.category ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))}
                />
              </Field>
              <Field label="Likelihood">
                <select
                  className="input"
                  value={draft.likelihood ?? "possible"}
                  onChange={(e) => setDraft((d) => ({ ...d, likelihood: e.target.value }))}
                >
                  {RISK_LIKELIHOOD.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Impact">
                <select
                  className="input"
                  value={draft.impact ?? "moderate"}
                  onChange={(e) => setDraft((d) => ({ ...d, impact: e.target.value }))}
                >
                  {RISK_IMPACT.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Severity">
                <select
                  className="input"
                  value={draft.severity ?? "medium"}
                  onChange={(e) => setDraft((d) => ({ ...d, severity: e.target.value }))}
                >
                  {RISK_SEVERITY.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Status">
                <select
                  className="input"
                  value={draft.status ?? "open"}
                  onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}
                >
                  {RISK_STATUSES.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Owner ID">
                <input
                  type="number"
                  className="input"
                  value={draft.owner_id ?? ""}
                  onChange={(e) =>
                    setDraft((d) => ({
                      ...d,
                      owner_id: e.target.value ? Number(e.target.value) : null,
                    }))
                  }
                />
              </Field>
              <Field label="Review date">
                <input
                  type="date"
                  className="input"
                  value={draft.review_date?.slice(0, 10) ?? ""}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, review_date: e.target.value || null }))
                  }
                />
              </Field>
            </div>
            <Field label="Description" className="mt-3">
              <textarea
                className="input min-h-[80px]"
                value={draft.description ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
              />
            </Field>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <Field label="Mitigation">
                <textarea
                  className="input min-h-[60px]"
                  value={draft.mitigation ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, mitigation: e.target.value }))}
                />
              </Field>
              <Field label="Contingency">
                <textarea
                  className="input min-h-[60px]"
                  value={draft.contingency ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, contingency: e.target.value }))}
                />
              </Field>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={cancel}>
                <IconX size={14} />
                Cancel
              </Button>
              <Button variant="primary" size="sm" onClick={submit}>
                <IconCheck size={14} />
                Save
              </Button>
            </div>
          </CardBody>
        </Card>
      )}
      <div className="space-y-2">
        {risks.map((risk) => (
          <Card key={risk.id} className="p-0">
            <CardBody className="p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h4 className="font-medium text-ink-primary">{risk.title}</h4>
                    <Badge tone={risk.severity === "critical" ? "danger" : "warning"}>
                      {risk.severity}
                    </Badge>
                    <Badge tone="outline">{risk.status}</Badge>
                  </div>
                  {risk.description && (
                    <p className="mt-1 text-sm text-ink-secondary">{risk.description}</p>
                  )}
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink-tertiary">
                    <span>Likelihood: {risk.likelihood}</span>
                    <span>Impact: {risk.impact}</span>
                    <span>Review: {risk.review_date ? fmtDate(risk.review_date) : "—"}</span>
                  </div>
                </div>
                {canEdit && (
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" onClick={() => startEdit(risk)} title="Edit">
                      <IconPencil size={14} />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setConfirmDelete(risk.id)}
                      title="Delete"
                    >
                      <IconTrash size={14} />
                    </Button>
                  </div>
                )}
              </div>
            </CardBody>
          </Card>
        ))}
        {risks.length === 0 && (
          <div className="text-sm text-ink-secondary">No risks defined yet.</div>
        )}
      </div>
      <ConfirmDialog
        open={confirmDelete !== null}
        title="Delete risk?"
        message="This will archive the risk. It can be restored later."
        confirmLabel="Delete"
        onConfirm={() => {
          if (confirmDelete !== null) onDelete(confirmDelete);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

interface MetricDraft {
  id?: number;
  name?: string;
  description?: string | null;
  business_definition?: string | null;
  unit?: string | null;
  format?: string | null;
  directionality?: string;
  aggregation?: string;
  source_type?: string | null;
  source_query_id?: number | null;
  source_mapping?: unknown;
  expression?: string | null;
  owner_id?: number | null;
  cadence?: string | null;
  position?: number;
  version?: number;
  targets?: Partial<ProjectMetricTarget>[];
}

function MetricsPanel({
  metrics,
  canEdit,
  onCreate,
  onUpdate,
  onDelete,
  onCreateTarget,
  onUpdateTarget,
  onDeleteTarget,
}: {
  metrics: ProjectMetric[];
  canEdit: boolean;
  onCreate: (body: Parameters<typeof createMetric>[1]) => void;
  onUpdate: (id: number, body: Parameters<typeof updateMetric>[2]) => void;
  onDelete: (id: number) => void;
  onCreateTarget: (metricId: number, body: Parameters<typeof createTarget>[2]) => void;
  onUpdateTarget: (metricId: number, targetId: number, body: Parameters<typeof updateTarget>[3]) => void;
  onDeleteTarget: (metricId: number, targetId: number) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<MetricDraft>({});
  const [confirmDelete, setConfirmDelete] = useState<{ metricId: number; targetId?: number } | null>(null);
  const [addingTarget, setAddingTarget] = useState<number | null>(null);
  const [targetDraft, setTargetDraft] = useState<Partial<ProjectMetricTarget>>({});
  const [editingTarget, setEditingTarget] = useState<{ metricId: number; targetId: number } | null>(null);

  const startEdit = (metric: ProjectMetric) => {
    setEditing(metric.id);
    setDraft({ ...metric });
  };

  const startAdd = () => {
    setAdding(true);
    setDraft({
      directionality: "higher_is_better",
      aggregation: "sum",
      targets: [],
    });
  };

  const submitMetric = () => {
    const body = {
      name: draft.name || "Untitled metric",
      description: draft.description || null,
      business_definition: draft.business_definition || null,
      unit: draft.unit || null,
      format: draft.format || null,
      directionality: draft.directionality || "higher_is_better",
      aggregation: draft.aggregation || "sum",
      source_type: draft.source_type || null,
      source_query_id: draft.source_query_id ?? null,
      source_mapping: draft.source_mapping ?? {},
      expression: draft.expression || null,
      owner_id: draft.owner_id ?? null,
      cadence: draft.cadence || null,
      targets: (draft.targets ?? []).filter(
        (t) => t.target_type,
      ) as Parameters<typeof createMetric>[1]["targets"],
    };
    if (editing) {
      onUpdate(editing, { ...body, expected_version: draft.version ?? 0 });
    } else {
      onCreate(body);
    }
    setAdding(false);
    setEditing(null);
    setDraft({});
  };

  const cancelMetric = () => {
    setAdding(false);
    setEditing(null);
    setDraft({});
  };

  const saveTarget = (metricId: number) => {
    const body = {
      target_type: targetDraft.target_type || "single_value",
      target_value: targetDraft.target_value ?? null,
      lower_bound: targetDraft.lower_bound ?? null,
      upper_bound: targetDraft.upper_bound ?? null,
      comparison_operator: targetDraft.comparison_operator || null,
      warning_threshold: targetDraft.warning_threshold ?? null,
      critical_threshold: targetDraft.critical_threshold ?? null,
      baseline: targetDraft.baseline ?? null,
      effective_start: targetDraft.effective_start || null,
      effective_end: targetDraft.effective_end || null,
      period: targetDraft.period || null,
      notes: targetDraft.notes || null,
      status: targetDraft.status || "draft",
    };
    if (editingTarget) {
      onUpdateTarget(metricId, editingTarget.targetId, { ...body, expected_version: targetDraft.version ?? 0 });
    } else {
      onCreateTarget(metricId, body);
    }
    setAddingTarget(null);
    setEditingTarget(null);
    setTargetDraft({});
  };

  const cancelTarget = () => {
    setAddingTarget(null);
    setEditingTarget(null);
    setTargetDraft({});
  };

  const startEditTarget = (metricId: number, target: ProjectMetricTarget) => {
    setEditingTarget({ metricId, targetId: target.id });
    setTargetDraft({ ...target });
  };

  return (
    <div className="space-y-3">
      {canEdit && !adding && !editing && (
        <div className="flex justify-end">
          <Button variant="primary" size="sm" onClick={startAdd}>
            <IconPlus size={14} />
            Add metric
          </Button>
        </div>
      )}
      {(adding || editing !== null) && (
        <Card>
          <CardHeader>
            <CardTitle>{editing ? "Edit metric" : "New metric"}</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Name">
                <input
                  className="input"
                  value={draft.name ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                />
              </Field>
              <Field label="Unit">
                <input
                  className="input"
                  value={draft.unit ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, unit: e.target.value }))}
                />
              </Field>
              <Field label="Directionality">
                <select
                  className="input"
                  value={draft.directionality ?? "higher_is_better"}
                  onChange={(e) => setDraft((d) => ({ ...d, directionality: e.target.value }))}
                >
                  {METRIC_DIRECTIONALITY.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Aggregation">
                <select
                  className="input"
                  value={draft.aggregation ?? "sum"}
                  onChange={(e) => setDraft((d) => ({ ...d, aggregation: e.target.value }))}
                >
                  {METRIC_AGGREGATIONS.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Format">
                <input
                  className="input"
                  value={draft.format ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, format: e.target.value }))}
                  placeholder="number, currency, percent"
                />
              </Field>
              <Field label="Cadence">
                <input
                  className="input"
                  value={draft.cadence ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, cadence: e.target.value }))}
                />
              </Field>
              <Field label="Owner ID">
                <input
                  type="number"
                  className="input"
                  value={draft.owner_id ?? ""}
                  onChange={(e) =>
                    setDraft((d) => ({
                      ...d,
                      owner_id: e.target.value ? Number(e.target.value) : null,
                    }))
                  }
                />
              </Field>
              <Field label="Source Query ID">
                <input
                  type="number"
                  className="input"
                  value={draft.source_query_id ?? ""}
                  onChange={(e) =>
                    setDraft((d) => ({
                      ...d,
                      source_query_id: e.target.value ? Number(e.target.value) : null,
                    }))
                  }
                />
              </Field>
            </div>
            <Field label="Business Definition" className="mt-3">
              <textarea
                className="input min-h-[60px]"
                value={draft.business_definition ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, business_definition: e.target.value }))}
              />
            </Field>
            <Field label="Expression / SQL reference" className="mt-3">
              <input
                className="input"
                value={draft.expression ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, expression: e.target.value }))}
              />
            </Field>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={cancelMetric}>
                <IconX size={14} />
                Cancel
              </Button>
              <Button variant="primary" size="sm" onClick={submitMetric}>
                <IconCheck size={14} />
                Save
              </Button>
            </div>
          </CardBody>
        </Card>
      )}
      <div className="space-y-3">
        {metrics.map((metric) => (
          <Card key={metric.id} className="p-0">
            <CardBody className="p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h4 className="font-medium text-ink-primary">{metric.name}</h4>
                    <Badge tone="brand">{metric.aggregation}</Badge>
                    <Badge tone="outline">{metric.directionality}</Badge>
                  </div>
                  {metric.business_definition && (
                    <p className="mt-1 text-sm text-ink-secondary">{metric.business_definition}</p>
                  )}
                </div>
                {canEdit && (
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" onClick={() => startEdit(metric)} title="Edit">
                      <IconPencil size={14} />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setConfirmDelete({ metricId: metric.id })}
                      title="Delete"
                    >
                      <IconTrash size={14} />
                    </Button>
                  </div>
                )}
              </div>

              <div className="mt-3">
                <div className="mb-2 flex items-center justify-between">
                  <h5 className="text-sm font-medium text-ink-primary">Targets</h5>
                  {canEdit && addingTarget !== metric.id && editingTarget?.metricId !== metric.id && (
                    <Button variant="brandSoft" size="sm" onClick={() => setAddingTarget(metric.id)}>
                      <IconPlus size={14} />
                      Add target
                    </Button>
                  )}
                </div>
                {(addingTarget === metric.id || editingTarget?.metricId === metric.id) && (
                  <div className="mb-3 rounded-md border border-line-tertiary bg-bg-primary p-3">
                    <div className="grid gap-3 md:grid-cols-3">
                      <Field label="Type">
                        <select
                          className="input"
                          value={targetDraft.target_type ?? "single_value"}
                          onChange={(e) =>
                            setTargetDraft((t) => ({ ...t, target_type: e.target.value }))
                          }
                        >
                          {TARGET_TYPES.map((x) => (
                            <option key={x} value={x}>
                              {x}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Target value">
                        <input
                          type="number"
                          step="any"
                          className="input"
                          value={targetDraft.target_value ?? ""}
                          onChange={(e) =>
                            setTargetDraft((t) => ({
                              ...t,
                              target_value: e.target.value ? Number(e.target.value) : null,
                            }))
                          }
                        />
                      </Field>
                      <Field label="Comparison">
                        <select
                          className="input"
                          value={targetDraft.comparison_operator ?? ""}
                          onChange={(e) =>
                            setTargetDraft((t) => ({
                              ...t,
                              comparison_operator: e.target.value || null,
                            }))
                          }
                        >
                          <option value="">—</option>
                          {COMPARISON_OPS.map((x) => (
                            <option key={x} value={x}>
                              {x}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Lower bound">
                        <input
                          type="number"
                          step="any"
                          className="input"
                          value={targetDraft.lower_bound ?? ""}
                          onChange={(e) =>
                            setTargetDraft((t) => ({
                              ...t,
                              lower_bound: e.target.value ? Number(e.target.value) : null,
                            }))
                          }
                        />
                      </Field>
                      <Field label="Upper bound">
                        <input
                          type="number"
                          step="any"
                          className="input"
                          value={targetDraft.upper_bound ?? ""}
                          onChange={(e) =>
                            setTargetDraft((t) => ({
                              ...t,
                              upper_bound: e.target.value ? Number(e.target.value) : null,
                            }))
                          }
                        />
                      </Field>
                      <Field label="Warning threshold">
                        <input
                          type="number"
                          step="any"
                          className="input"
                          value={targetDraft.warning_threshold ?? ""}
                          onChange={(e) =>
                            setTargetDraft((t) => ({
                              ...t,
                              warning_threshold: e.target.value ? Number(e.target.value) : null,
                            }))
                          }
                        />
                      </Field>
                      <Field label="Critical threshold">
                        <input
                          type="number"
                          step="any"
                          className="input"
                          value={targetDraft.critical_threshold ?? ""}
                          onChange={(e) =>
                            setTargetDraft((t) => ({
                              ...t,
                              critical_threshold: e.target.value ? Number(e.target.value) : null,
                            }))
                          }
                        />
                      </Field>
                      <Field label="Baseline">
                        <input
                          type="number"
                          step="any"
                          className="input"
                          value={targetDraft.baseline ?? ""}
                          onChange={(e) =>
                            setTargetDraft((t) => ({
                              ...t,
                              baseline: e.target.value ? Number(e.target.value) : null,
                            }))
                          }
                        />
                      </Field>
                      <Field label="Effective start">
                        <input
                          type="date"
                          className="input"
                          value={targetDraft.effective_start?.slice(0, 10) ?? ""}
                          onChange={(e) =>
                            setTargetDraft((t) => ({
                              ...t,
                              effective_start: e.target.value || null,
                            }))
                          }
                        />
                      </Field>
                      <Field label="Effective end">
                        <input
                          type="date"
                          className="input"
                          value={targetDraft.effective_end?.slice(0, 10) ?? ""}
                          onChange={(e) =>
                            setTargetDraft((t) => ({
                              ...t,
                              effective_end: e.target.value || null,
                            }))
                          }
                        />
                      </Field>
                    </div>
                    <Field label="Notes" className="mt-3">
                      <textarea
                        className="input min-h-[60px]"
                        value={targetDraft.notes ?? ""}
                        onChange={(e) => setTargetDraft((t) => ({ ...t, notes: e.target.value }))}
                      />
                    </Field>
                    <div className="mt-3 flex justify-end gap-2">
                      <Button variant="ghost" size="sm" onClick={cancelTarget}>
                        Cancel
                      </Button>
                      <Button variant="primary" size="sm" onClick={() => saveTarget(metric.id)}>
                        Save target
                      </Button>
                    </div>
                  </div>
                )}
                <div className="space-y-2">
                  {metric.targets?.map((target) => (
                    <div
                      key={target.id}
                      className="flex items-center justify-between rounded-md border border-line-tertiary px-3 py-2"
                    >
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="font-medium">{target.target_type}</span>
                        <span className="text-ink-secondary">value: {target.target_value ?? "—"}</span>
                        <span className="text-ink-secondary">
                          {target.comparison_operator} {target.warning_threshold ?? "—"} warn /{" "}
                          {target.critical_threshold ?? "—"} crit
                        </span>
                        <Badge tone="outline" size="sm">
                          {target.status}
                        </Badge>
                      </div>
                      {canEdit && (
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => startEditTarget(metric.id, target)}
                          >
                            <IconPencil size={14} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setConfirmDelete({ metricId: metric.id, targetId: target.id })}
                          >
                            <IconTrash size={14} />
                          </Button>
                        </div>
                      )}
                    </div>
                  ))}
                  {(!metric.targets || metric.targets.length === 0) && (
                    <div className="text-sm text-ink-secondary">No targets for this metric.</div>
                  )}
                </div>
              </div>
            </CardBody>
          </Card>
        ))}
        {metrics.length === 0 && (
          <div className="text-sm text-ink-secondary">No metrics defined yet.</div>
        )}
      </div>
      <ConfirmDialog
        open={confirmDelete !== null}
        title={confirmDelete?.targetId ? "Delete target?" : "Delete metric?"}
        message="This will archive the item. It can be restored later."
        confirmLabel="Delete"
        onConfirm={() => {
          if (confirmDelete) {
            if (confirmDelete.targetId) {
              onDeleteTarget(confirmDelete.metricId, confirmDelete.targetId);
            } else {
              onDelete(confirmDelete.metricId);
            }
          }
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

function AuditPanel({
  events,
  total,
}: {
  events: ProjectContextAuditEvent[];
  total: number;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Audit History ({total})</CardTitle>
      </CardHeader>
      <CardBody>
        <div className="space-y-2">
          {events.map((event) => (
            <div
              key={event.id}
              className="flex flex-col gap-1 rounded-md border border-line-tertiary px-3 py-2 text-sm"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-ink-primary">{event.event_type}</span>
                <span className="text-xs text-ink-tertiary">{fmtDate(event.created_at)}</span>
              </div>
              <div className="text-ink-secondary">
                Entity: {event.entity_type} #{event.entity_id ?? "—"} | Actor: {event.actor_type} #{event.actor_user_id ?? "system"}
              </div>
              {event.version != null && (
                <div className="text-xs text-ink-tertiary">Version: {event.version}</div>
              )}
            </div>
          ))}
          {events.length === 0 && (
            <div className="text-sm text-ink-secondary">No audit events yet.</div>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-tertiary">
        {label}
      </span>
      {children}
    </label>
  );
}


