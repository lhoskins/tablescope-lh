"use client";

import { useMemo } from "react";
import {
  IconSparkles,
  IconChartBar,
  IconTable,
} from "@tabler/icons-react";
import { MessageTimestamp } from "@/app/ai/message-timestamp";
import { ResponsePresenter } from "@/components/ai/ResponsePresenter";
import type { ResponseEnvelope, SuggestedVisualization } from "@/lib/api/ai-actions";
import type { ConversationTurn } from "@/lib/api/conversational-analytics";
import { MatchedInsightBlock } from "./matched-insight-block";

const CHART_FOLLOW_UPS = [
  "change it to a line chart",
  "change it to a bar chart",
  "change it to a horizontal bar chart",
  "change it to a donut chart",
  "sort by value descending",
  "show as a table",
];

function buildEnvelope(turn: ConversationTurn): ResponseEnvelope | null {
  if (!turn.result && !turn.chart_config && !turn.sql) return null;
  const result = turn.result;
  const columns = result?.columns ?? [];
  const rows = (result?.rows ?? []) as Record<string, unknown>[];
  const chart: SuggestedVisualization | undefined = turn.chart_config
    ? {
        type: turn.chart_config.type as SuggestedVisualization["type"],
        xField: turn.chart_config.labelColumn,
        yField: turn.chart_config.valueColumns?.[0],
        // Dual-axis families (combo, actual-vs-target, co-movement) carry a
        // second measure; dropping it rendered them as a single series.
        y2Field: turn.chart_config.valueColumns?.[1],
        chartStyle: turn.chart_config.subtype,
        metricField: turn.chart_config.metricField,
        topN: turn.chart_config.topN,
        valueFormat: turn.chart_config.valueFormat,
      }
    : undefined;

  return {
    mode: "data",
    sections: ["summary", "chart", "grid", "show_sql"],
    summary: turn.assistant_message ?? undefined,
    answer: turn.assistant_message ?? undefined,
    sql: turn.sql ?? undefined,
    columns,
    rows,
    chart,
    status: turn.status,
  } as ResponseEnvelope;
}

export function TurnBubble({
  turn,
  onFollowUp,
  isLast,
}: {
  turn: ConversationTurn;
  onFollowUp?: (text: string) => void;
  isLast?: boolean;
}) {
  const envelope = useMemo<ResponseEnvelope | null>(() => buildEnvelope(turn), [turn]);
  const assistantTimestamp = turn.status === "pending" ? null : turn.updated_at;
  return (
    <div className="space-y-2">
      <div className="group flex flex-col items-end">
        <div className="max-w-[80%] rounded-lg bg-brand px-3.5 py-2.5 text-[13px] leading-relaxed text-brand-fg">
          {turn.user_message}
        </div>
        <MessageTimestamp value={turn.created_at} label="Sent" align="right" />
      </div>
      <div className="group flex gap-2.5">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
          <IconSparkles size={15} />
        </div>
        <div className="max-w-[80%] min-w-0 flex-1">
          <div className="rounded-lg border border-line-tertiary bg-bg-primary px-3.5 py-2.5 text-[13px] leading-relaxed text-ink-primary">
            {turn.status === "error" ? (
              <p className="text-red-600">{turn.assistant_message}</p>
            ) : (
              <>
                {envelope ? (
                  <ResponsePresenter envelope={envelope} />
                ) : (
                  <p className="mb-2 whitespace-pre-wrap">{turn.assistant_message}</p>
                )}
                {turn.matched_insight && (
                  <MatchedInsightBlock match={turn.matched_insight} />
                )}
              </>
            )}
          </div>
          <MessageTimestamp value={assistantTimestamp} label="Answered" align="left" />
        </div>
      </div>
      {isLast && turn.status === "success" && envelope && onFollowUp && (
        <div className="ml-10 flex flex-wrap gap-2">
          {CHART_FOLLOW_UPS.map((text) => (
            <button
              key={text}
              type="button"
              onClick={() => onFollowUp(text)}
              aria-label={text}
              className="inline-flex items-center gap-1 rounded-full border border-line-tertiary bg-bg-secondary px-2 py-1 text-[11px] text-ink-secondary hover:border-brand-500 hover:text-ink-primary"
            >
              {text.includes("table") ? <IconTable size={11} /> : <IconChartBar size={11} />}
              {text}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
