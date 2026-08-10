"use client";

import Link from "next/link";
import { IconArrowUpRight, IconTargetArrow } from "@tabler/icons-react";
import { InsightChartView } from "@/components/tablescope/home/intelligence-card/insight-chart-view";
import type { MatchedInsight } from "@/lib/api/conversational-analytics";

const ACTION_KIND_LABELS: Record<string, string> = {
  mitigate: "Mitigate",
  capture: "Capture",
  monitor: "Monitor",
  investigate: "Investigate",
};

function DiagnosticStep({
  diagnostic,
}: {
  diagnostic: NonNullable<MatchedInsight["diagnostics"]>[number];
}) {
  return (
    <li className="space-y-0.5">
      <p className="text-[13px] font-medium text-ink-primary">
        {diagnostic.title}
      </p>
      {diagnostic.question ? (
        <p className="text-[12px] text-ink-tertiary">{diagnostic.question}</p>
      ) : null}
      {diagnostic.finding ? (
        <p className="text-[13px] text-ink-secondary">{diagnostic.finding}</p>
      ) : null}
      {diagnostic.highlight ? (
        <p className="text-[13px] font-semibold text-ink-primary">
          {diagnostic.highlight}
        </p>
      ) : null}
    </li>
  );
}

function ProposedActionItem({
  action,
}: {
  action: NonNullable<MatchedInsight["proposedActions"]>[number];
}) {
  return (
    <li className="flex items-start gap-1.5 text-[13px] text-ink-secondary">
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
          <span className="ml-1 text-ink-tertiary">(needs confirmation)</span>
        ) : null}
      </span>
    </li>
  );
}

/**
 * Points a chat turn back at an existing, verified Insight Card instead of
 * a fresh (and here, unanswerable) SQL guess — the real chart from that
 * card's analysis, plus its grounded full analysis and proposed actions.
 */
export function MatchedInsightBlock({ match }: { match: MatchedInsight }) {
  const diagnostics = (match.diagnostics ?? []).filter(
    (d) => !d.title?.startsWith("Claim:"),
  );
  const actions = (match.proposedActions ?? []).filter(
    (a) => a.kind !== "investigate",
  );

  return (
    <div className="mt-2 w-full rounded-xl border border-line-tertiary bg-bg-primary p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-ink-tertiary">
            {match.projectName || "Existing insight"}
          </p>
          <p className="mt-0.5 truncate text-[13px] font-semibold text-ink-primary">
            {match.title}
          </p>
        </div>
        <Link
          href={`/business-insight/analysis/${encodeURIComponent(match.insightId)}`}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line-secondary px-2 py-1 text-[12px] font-medium text-brand-700 hover:border-brand-500"
        >
          Explore full analysis
          <IconArrowUpRight size={14} />
        </Link>
      </div>

      {match.summary ? (
        <p className="mt-2 text-[13px] text-ink-secondary">{match.summary}</p>
      ) : null}

      {match.chart && (
        <div className="mt-3">
          <InsightChartView chart={match.chart} height={220} />
        </div>
      )}

      {diagnostics.length > 0 && (
        <div className="mt-3 rounded-lg border border-line-tertiary bg-bg-secondary/60 p-3">
          <p className="text-[12px] font-medium uppercase tracking-wide text-ink-tertiary">
            Full analysis
          </p>
          <ul className="mt-2 space-y-2">
            {diagnostics.map((d, idx) => (
              <DiagnosticStep key={idx} diagnostic={d} />
            ))}
          </ul>
        </div>
      )}

      {actions.length > 0 && (
        <div className="mt-3 rounded-lg border border-line-tertiary bg-bg-secondary/60 p-3">
          <p className="text-[12px] font-medium uppercase tracking-wide text-ink-tertiary">
            Proposed actions
          </p>
          <ul className="mt-2 space-y-2">
            {actions.map((a, idx) => (
              <ProposedActionItem key={idx} action={a} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
