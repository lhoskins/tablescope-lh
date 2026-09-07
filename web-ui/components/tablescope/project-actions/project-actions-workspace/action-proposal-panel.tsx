"use client";

import { useState } from "react";
import Link from "next/link";
import { IconCircleCheck, IconSparkles, IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import type { ProjectAction, ReviewProjectActionPayload } from "@/lib/api/project-actions";

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "—";
}

export function ActionProposalPanel({
  projectId,
  action,
  canManage,
  reviewing,
  onReview,
}: {
  projectId: string;
  action: ProjectAction;
  canManage: boolean;
  reviewing: boolean;
  onReview: (payload: ReviewProjectActionPayload) => void;
}) {
  const [note, setNote] = useState("");
  const [reviewDate, setReviewDate] = useState("");
  const meta = action.proposal_metadata ?? {};
  const criteria = Array.isArray(meta.successCriteria) ? meta.successCriteria : [];
  const first = (criteria[0] ?? {}) as Record<string, unknown>;
  const sourceHref = action.source_surface === "project_insight"
    ? `/projects/${projectId}/insight`
    : action.source_insight_id
      ? `/business-insight/analysis/${action.source_insight_id}`
      : `/projects/${projectId}/insight`;

  return (
    <section className="space-y-4 rounded-lg border border-brand-200 bg-brand-50/40 p-4" aria-label="AI action proposal review">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[13px] font-semibold text-brand-700">
            <IconSparkles size={16} /> AI-proposed action · Human approval required
          </div>
          <p className="mt-1 text-[12px] text-ink-secondary">
            Grounded in <Link className="font-medium text-brand-600 hover:underline" href={sourceHref}>{action.source_insight_title ?? "the source insight"}</Link>
          </p>
        </div>
        <span className="rounded-full bg-warning-bg px-2.5 py-1 text-[11px] font-semibold text-warning">Pending review</span>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <ProposalField label="Goal / success criterion" value={text(first.name ?? meta.goalTitle)} />
        <ProposalField label="KPI" value={text(first.metric ?? first.name ?? meta.metricName)} />
        <ProposalField label="Baseline" value={text(first.baseline_value ?? first.baseline ?? meta.baseline)} />
        <ProposalField label="Target & cadence" value={`${text(first.target_value ?? meta.target)} · ${text(first.cadence ?? meta.cadence)}`} />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <ProposalField label="Measurement" value={text(first.description ?? meta.measurement)} />
        <ProposalField label="Reviewer" value={action.reviewer_user_id ? `User ${action.reviewer_user_id}` : "Project owner"} />
        <ProposalField label="Duplicate check" value={text(meta.duplicateCheck)} />
      </div>

      {action.subtasks.length > 0 && (
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">Proposed steps</p>
          <ol className="grid gap-2 md:grid-cols-2">
            {action.subtasks.filter((item) => !item.archived_at).map((item, index) => (
              <li key={item.id} className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[12px] text-ink-primary">
                <span className="mr-2 font-semibold text-brand-600">{index + 1}.</span>{item.title}
              </li>
            ))}
          </ol>
        </div>
      )}

      {canManage && (
        <div className="space-y-3 border-t border-line-tertiary pt-3">
          <div className="grid gap-2 md:grid-cols-[1fr_180px]">
            <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Manager note (optional)" className="min-h-9 rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[12px]" />
            <input type="date" value={reviewDate} onChange={(event) => setReviewDate(event.target.value)} aria-label="Defer until" className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[12px]" />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="primary" disabled={reviewing} onClick={() => onReview({ decision: "accept", note, expected_version: action.lock_version })}><IconCircleCheck size={15} /> Accept</Button>
            <Link className="inline-flex h-7 items-center rounded-md border border-line-secondary bg-bg-primary px-2.5 text-[12px] font-medium text-ink-primary hover:bg-bg-secondary" href={`/projects/${projectId}/actions/${action.id}?review=1`}>Edit &amp; accept</Link>
            <Button size="sm" variant="secondary" disabled={reviewing || !reviewDate} onClick={() => onReview({ decision: "defer", note, review_due_at: new Date(`${reviewDate}T12:00:00Z`).toISOString(), expected_version: action.lock_version })}>Defer</Button>
            <Button size="sm" variant="secondary" disabled={reviewing} onClick={() => onReview({ decision: "reject", note, expected_version: action.lock_version })}><IconX size={15} /> Reject</Button>
          </div>
        </div>
      )}
    </section>
  );
}

function ProposalField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line-tertiary bg-bg-primary p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-tertiary">{label}</p>
      <p className="mt-1 text-[12px] font-medium text-ink-primary">{value}</p>
    </div>
  );
}
