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
import { useProjectMembers, type ProjectMember } from "@/lib/ui/use-project-data";import { RisksSectionProps } from "./risks-section-props";
import { InlineRiskForm } from "./inline-risk-form";
import { RiskRow } from "./risk-row";



export function RisksSection({ risks, memberMap, canEdit, onCreateRisk, onUpdateRisk, onDeleteRisk }: RisksSectionProps) {
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