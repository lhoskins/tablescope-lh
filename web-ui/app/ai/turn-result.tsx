"use client";


import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconArrowUp,
  IconSparkles,
  IconPlus,
  IconTrash,
  IconRefresh,
  IconDots,
  IconPencil,
} from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import { cn } from "@/lib/cn";
import { getUserMeta } from "@/lib/auth";
import { useCurrentUser, useProjectSummaries } from "@/lib/ui/use-shell-data";
import {
  createConversation,
  listConversations,
  getConversation,
  submitTurn,
  renameConversation,
  deleteConversation,
  type Conversation,
  type ConversationSummary,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";
import { ResultChart, ResultTable } from "@/components/ai/ai-result-view";
import type { SuggestedVisualization } from "@/lib/api/ai-actions";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";


export function TurnResult({ turn }: { turn: ConversationTurn }) {
  const [showSql, setShowSql] = useState(false);
  const result = turn.result;
  if (!result) return null;
  const chart = turn.chart_config;
  // Map the persisted chart config onto the shared renderer contract; the
  // subtype (horizontal_bar, donut, …) rides through as chartStyle.
  const viz: SuggestedVisualization = chart
    ? {
        type: chart.type as SuggestedVisualization["type"],
        xField: chart.labelColumn,
        yField: chart.valueColumns?.[0],
        chartStyle: chart.subtype,
      }
    : { type: "table" };
  return (
    <div className="mt-2 rounded-xl border border-line-tertiary bg-bg-primary p-3">
      {chart && chart.type !== "table" && (
        <ResultChart columns={result.columns} rows={result.rows} viz={viz} />
      )}
      <ResultTable columns={result.columns} rows={result.rows} />
      {turn.sql && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setShowSql((v) => !v)}
            className="text-[11px] text-ink-tertiary hover:text-ink-secondary"
          >
            {showSql ? "Hide SQL" : "Show SQL"}
          </button>
          {showSql && (
            <pre className="mt-1 overflow-auto rounded-md bg-bg-secondary p-2 text-[11px] text-ink-secondary">
              {turn.sql}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}