"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  IconChevronRight,
  IconMessageQuestion,
  IconSparkles,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  getRecentProjectConversations,
  type RecentConversationItem,
} from "@/lib/api/conversational-analytics";
import { timeAgo } from "@/lib/ui/format";
import { buildAiAssistantHref } from "@/lib/navigation/ai-assistant";

export const RECENT_CONVERSATIONS_LIMIT = 4;

/** Query key for the panel; project-scoped so switching projects never shows
 *  another project's rows while loading. */
export function recentConversationsKey(projectId: string) {
  return ["project", projectId, "ai-conversations", "recent"] as const;
}

export function conversationHref(
  projectId: string,
  item: RecentConversationItem,
) {
  return buildAiAssistantHref({
    projectId,
    conversationId: item.conversation_id,
    turnId: item.turn_id,
    origin: "project-overview",
  });
}

export function AiConversationsCard({ projectId }: { projectId: string }) {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: recentConversationsKey(projectId),
    queryFn: () =>
      getRecentProjectConversations(projectId, RECENT_CONVERSATIONS_LIMIT),
    enabled: Boolean(projectId),
  });

  const items = data?.items ?? [];

  return (
    <section
      aria-label="AI Assistant conversations"
      className="flex flex-col rounded-lg border border-line-tertiary bg-bg-primary"
    >
      <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
        <h2 className="text-h3 text-ink-primary">AI Assistant conversations</h2>
      </div>
      <div className="flex-1 p-2">
        {isLoading ? (
          <ul className="space-y-1" aria-hidden>
            {Array.from({ length: RECENT_CONVERSATIONS_LIMIT }).map((_, i) => (
              <li
                key={i}
                className="px-2 py-2"
                data-testid="conversation-skeleton"
              >
                <div className="h-3.5 w-3/4 animate-pulse rounded bg-bg-secondary" />
                <div className="mt-1.5 h-3 w-1/2 animate-pulse rounded bg-bg-secondary" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <div className="px-2 py-8 text-center">
            <p className="text-small text-ink-secondary">
              Unable to load conversations
            </p>
            <Button
              variant="secondary"
              size="sm"
              className="mt-2"
              disabled={isFetching}
              onClick={() => void refetch()}
            >
              Retry
            </Button>
          </div>
        ) : items.length === 0 ? (
          <div className="px-2 py-8 text-center">
            <p className="text-[13px] font-medium text-ink-primary">
              No project conversations yet
            </p>
            <p className="mt-1 text-small text-ink-tertiary">
              Ask a question above to begin this project&apos;s AI Assistant
              history.
            </p>
          </div>
        ) : (
          <ul className="space-y-0.5">
            {items.map((item) => (
              <li key={`${item.conversation_id}-${item.turn_id}`}>
                <Link
                  href={conversationHref(projectId, item)}
                  aria-label={`Open AI Assistant conversation: ${item.question_preview}`}
                  className="group flex min-h-[44px] items-start gap-2.5 rounded-md px-2 py-2 hover:bg-bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500"
                >
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700">
                    <IconMessageQuestion size={14} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-ink-primary group-hover:text-brand-700">
                      {item.question_preview}
                    </span>
                    <span className="mt-0.5 flex items-start gap-1.5 text-small text-ink-tertiary">
                      <IconSparkles
                        size={12}
                        className="mt-0.5 shrink-0 text-ai"
                      />
                      <span className="line-clamp-2">
                        {item.result_preview}
                      </span>
                    </span>
                  </span>
                  <span
                    className="shrink-0 text-small text-ink-tertiary"
                    title={new Date(item.completed_at).toLocaleString()}
                  >
                    {timeAgo(item.completed_at)}
                  </span>
                  <IconChevronRight
                    size={14}
                    className="mt-1 shrink-0 text-ink-tertiary"
                    aria-hidden
                  />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="border-t border-line-tertiary px-4 py-2.5">
        <Link
          href={buildAiAssistantHref({
            projectId,
            origin: "project-overview",
          })}
          className="text-[12px] font-medium text-brand-700 hover:underline"
        >
          View all project conversations →
        </Link>
      </div>
    </section>
  );
}
