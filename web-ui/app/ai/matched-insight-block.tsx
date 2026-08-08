"use client";

import Link from "next/link";
import { IconArrowUpRight } from "@tabler/icons-react";
import { InsightChartView } from "@/components/tablescope/home/intelligence-card/insight-chart-view";
import type { MatchedInsight } from "@/lib/api/conversational-analytics";

/**
 * Points a chat turn back at an existing, verified Insight Card instead of
 * a fresh (and here, unanswerable) SQL guess — the real chart from that
 * card's analysis, plus a breadcrumb to explore it in full.
 */
export function MatchedInsightBlock({ match }: { match: MatchedInsight }) {
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
          href={`/business-insight/analysis/${match.insightId}`}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line-secondary px-2 py-1 text-[12px] font-medium text-brand-700 hover:border-brand-500"
        >
          Explore full analysis
          <IconArrowUpRight size={14} />
        </Link>
      </div>
      {match.chart && (
        <div className="mt-3">
          <InsightChartView chart={match.chart} height={220} />
        </div>
      )}
    </div>
  );
}
