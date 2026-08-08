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
import { useProjectMembers, type ProjectMember } from "@/lib/ui/use-project-data";import { fmtDate } from "./fmt-date";
import { riskSeverityTone } from "./risk-severity-tone";
import { riskStatusTone } from "./risk-status-tone";
import { likelihoodTone } from "./likelihood-tone";
import { impactTone } from "./impact-tone";
import { displayName } from "./display-name";
import { initials } from "./initials";
import { InlineRiskForm } from "./inline-risk-form";



export function RiskRow({
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