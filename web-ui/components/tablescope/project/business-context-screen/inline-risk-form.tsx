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
import { useProjectMembers, type ProjectMember } from "@/lib/ui/use-project-data";import { RISK_LIKELIHOOD } from "./risk-likelihood";
import { RISK_IMPACT } from "./risk-impact";
import { RISK_STATUSES } from "./risk-statuses";



export function InlineRiskForm({
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