"use client";

import { IconSparkles } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import type { ConversationTurn } from "@/lib/api/conversational-analytics";
import { MatchedInsightBlock } from "@/components/tablescope/conversation/matched-insight-block";
import { MessageTimestamp } from "./message-timestamp";
import { TurnResult } from "./turn-result";
import { UserBubble } from "./user-bubble";

/** One conversational-analytics turn: the user's message + the AI answer. */
export function TurnBubbles({ turn }: { turn: ConversationTurn }) {
  const result = turn.result;
  const hasData = (result?.rows?.length ?? 0) > 0;
  const matched = turn.matched_insight;
  const assistantTimestamp =
    turn.status === "pending" ? null : turn.updated_at;

  return (
    <>
      <UserBubble content={turn.user_message} timestamp={turn.created_at} />
      <div className="group flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
          <IconSparkles size={16} />
        </div>
        <div
          className={cn(
            "flex flex-col",
            hasData || matched ? "w-full" : "max-w-[75%]",
          )}
        >
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
          <MessageTimestamp
            value={assistantTimestamp}
            label="Answered"
            align="left"
          />
          {hasData && result && <TurnResult turn={turn} />}
          {matched && <MatchedInsightBlock match={matched} />}
        </div>
      </div>
    </>
  );
}
