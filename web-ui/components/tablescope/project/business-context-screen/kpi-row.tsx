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
import { fmtNumber } from "./fmt-number";
import { metricTrendMeta } from "./metric-trend-meta";
import { matchStatusTone } from "./match-status-tone";
import { formatTarget } from "./format-target";
import { metricIcon } from "./metric-icon";
import { KpiDraftState } from "./kpi-draft-state";



export function KpiRow({
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