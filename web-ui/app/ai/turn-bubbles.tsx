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
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";import { UserBubble } from "./user-bubble";
import { TurnResult } from "./turn-result";
import { MatchedInsightBlock } from "@/components/tablescope/conversation/matched-insight-block";



/** One conversational-analytics turn: the user's message + the AI answer. */
export function TurnBubbles({ turn }: { turn: ConversationTurn }) {
  const result = turn.result;
  const hasData = (result?.rows?.length ?? 0) > 0;
  const matched = turn.matched_insight;
  return (
    <>
      <UserBubble content={turn.user_message} />
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
          <IconSparkles size={16} />
        </div>
        <div className={cn("flex flex-col", hasData || matched ? "w-full" : "max-w-[75%]")}>
          <div
            className={cn(
              "rounded-xl bg-bg-secondary px-4 py-3 text-[13px] leading-relaxed",
              turn.status === "error" ? "text-danger" : "text-ink-primary",
            )}
          >
            <span className="whitespace-pre-wrap break-words">
              {turn.assistant_message ??
                (turn.status === "pending" ? "Working on it…" : "")}
            </span>
          </div>
          {hasData && result && <TurnResult turn={turn} />}
          {matched && <MatchedInsightBlock match={matched} />}
        </div>
      </div>
    </>
  );
}