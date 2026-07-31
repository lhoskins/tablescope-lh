"use client";

import Link from "next/link";
import { IconArrowRight, IconTargetArrow } from "@tabler/icons-react";
import type { InsightCard, ProposedAction } from "@/lib/api/home-intelligence";

/**
 * Compact Deeper-analysis summary shown on an insight card.
 *
 * The card stays scannable: one line of what the dissection found, one line of
 * what to do about it, and a link to the full analysis. The depth — the whole
 * diagnostic ladder, cross-references and the card-scoped ask box — lives on the
 * shareable route rather than inflating every card in the feed.
 *
 * Renders nothing when a card has not been dissected, so a card never
 * advertises an analysis that does not exist.
 */
const ACTION_KIND_LABELS: Record<string, string> = {
  mitigate: "Mitigate",
  capture: "Capture",
  investigate: "Investigate",
  monitor: "Monitor",
};

export function InsightAnalysisStrip({ card }: { card: InsightCard }) {
  const diagnostics = card.diagnostics ?? [];
  const actions = card.proposedActions ?? [];
  if (diagnostics.length === 0) return null;

  const insightId = card.insightId ?? card.id;
  const lead =
    diagnostics.find((d) => !d.title?.startsWith("Claim:")) ?? diagnostics[0];
  const action =
    actions.find((a) => a.kind !== "investigate") ??
    (actions[0] as ProposedAction | undefined);

  return (
    <div className="mt-3 rounded-lg border border-line-tertiary bg-bg-secondary/60 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <p className="text-[13px] text-ink-secondary">
            <span className="font-medium text-ink-primary">{lead.title}:</span>{" "}
            {lead.finding}
          </p>
          {action ? (
            <p className="flex items-start gap-1.5 text-[13px] text-ink-secondary">
              <IconTargetArrow
                size={15}
                className="mt-0.5 shrink-0 text-brand-600"
                aria-hidden
              />
              <span>
                <span className="font-medium text-ink-primary">{action.headline}</span>
                {ACTION_KIND_LABELS[action.kind] ? (
                  <span className="ml-1 rounded bg-bg-tertiary px-1.5 py-0.5 text-[11px] font-medium text-ink-tertiary">
                    {ACTION_KIND_LABELS[action.kind]}
                  </span>
                ) : null}
                {action.confidence === "low" ? (
                  <span className="ml-1 text-ink-tertiary">
                    (needs confirmation)
                  </span>
                ) : null}
              </span>
            </p>
          ) : null}
        </div>
        <Link
          href={`/business-insight/analysis/${encodeURIComponent(insightId)}`}
          className="shrink-0 inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1.5 text-[13px] font-medium text-ink-secondary transition-colors hover:bg-bg-primary hover:text-ink-primary"
          aria-label={`Full analysis of ${card.title}`}
        >
          Full analysis
          <IconArrowRight size={14} aria-hidden />
        </Link>
      </div>
      {diagnostics.length > 1 ? (
        <p className="mt-2 text-[12px] text-ink-tertiary">
          {diagnostics.length} diagnostic steps
          {actions.length > 1 ? ` · ${actions.length} proposed actions` : ""}
        </p>
      ) : null}
    </div>
  );
}
