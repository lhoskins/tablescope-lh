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
import { useProjectMembers, type ProjectMember } from "@/lib/ui/use-project-data";import { GOAL_STATUSES } from "./goal-statuses";



export function InlineGoalForm({
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