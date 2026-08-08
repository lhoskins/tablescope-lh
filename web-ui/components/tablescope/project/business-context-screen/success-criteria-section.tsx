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
import { useProjectMembers, type ProjectMember } from "@/lib/ui/use-project-data";import { METRIC_DIRECTIONALITY } from "./metric-directionality";
import { fmtDate } from "./fmt-date";
import { fmtDateShort } from "./fmt-date-short";
import { goalProgress } from "./goal-progress";
import { goalDeleteImpact } from "./goal-delete-impact";
import { goalStatusTone } from "./goal-status-tone";
import { displayName } from "./display-name";
import { initials } from "./initials";
import { KpiDraftState } from "./kpi-draft-state";
import { SuccessCriteriaSectionProps } from "./success-criteria-section-props";
import { InlineGoalForm } from "./inline-goal-form";
import { KpiRow } from "./kpi-row";



export function SuccessCriteriaSection({
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