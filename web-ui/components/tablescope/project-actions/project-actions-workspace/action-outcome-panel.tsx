import Link from "next/link";
import { IconRefresh, IconTargetArrow } from "@tabler/icons-react";
import type { ProjectAction } from "@/lib/api/project-actions";

export function ActionOutcomePanel({ projectId, action }: { projectId: string; action: ProjectAction }) {
  const updated = (action.outcome_snapshot?.updatedInsight ?? null) as Record<string, unknown> | null;
  const surfaces = (action.outcome_snapshot?.surfaces ?? {}) as Record<string, Record<string, unknown>>;
  const href = action.source_surface === "project_insight"
    ? `/projects/${projectId}/insight`
    : action.source_insight_id
      ? `/business-insight/analysis/${action.source_insight_id}`
      : `/projects/${projectId}/insight`;
  if (!updated) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-line-tertiary bg-bg-primary p-3 text-[12px] text-ink-secondary">
        <IconRefresh size={16} /> Outcome is awaiting the next Business or Project Insight refresh.
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-success/20 bg-success-bg p-4">
      <div className="flex items-center gap-2 text-[13px] font-semibold text-success"><IconTargetArrow size={17} /> Grounded result from refreshed insight</div>
      <p className="mt-2 text-[13px] font-medium text-ink-primary">{String(updated.title ?? action.source_insight_title ?? "Updated insight")}</p>
      <p className="mt-1 text-[12px] text-ink-secondary">{String(updated.summary ?? "The refreshed insight card is now linked as the measured outcome.")}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {Object.keys(surfaces).map((surface) => (
          <span key={surface} className="rounded-full bg-bg-primary px-2 py-1 text-[11px] text-ink-secondary">
            {surface === "business_insight" ? "Business Insight" : "Project Insight"} refreshed
          </span>
        ))}
      </div>
      <Link href={href} className="mt-2 inline-block text-[12px] font-medium text-brand-600 hover:underline">Open updated insight card</Link>
    </div>
  );
}
