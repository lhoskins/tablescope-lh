"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  IconAlertTriangle,
  IconTrendingUp,
  IconBulb,
  IconChartBar,
  IconMessageQuestion,
} from "@tabler/icons-react";
import { Card } from "@/components/ui/card";
import { getRecentProjectConversations } from "@/lib/api/conversational-analytics";
import {
  recentConversationsKey,
  conversationHref,
  RECENT_CONVERSATIONS_LIMIT,
} from "@/components/tablescope/project/ai-conversations-card";
import { timeAgo } from "@/lib/ui/format";
import { buildAiAssistantHref } from "@/lib/navigation/ai-assistant";
import type { ProjectInsightCard } from "@/lib/api/project-insight";
import { insightCategory } from "./insight-category";

/** Combined view of Project Insight cards + recent AI Assistant turns, newest
 *  first, so the page shows one activity feed instead of two separate lists
 *  competing for attention. */
const FEED_LIMIT = 6;

type InsightKind = "risk" | "trend" | "opportunity" | "analysis";

interface FeedRow {
  key: string;
  kind: InsightKind | "conversation";
  title: string;
  detail: string;
  ts: string;
  href: string;
}

const ICON_STYLE: Record<FeedRow["kind"], { icon: typeof IconAlertTriangle; iconClass: string }> = {
  risk: { icon: IconAlertTriangle, iconClass: "bg-danger-bg text-danger" },
  trend: { icon: IconTrendingUp, iconClass: "bg-warning-bg text-warning" },
  opportunity: { icon: IconBulb, iconClass: "bg-success-bg text-success" },
  analysis: { icon: IconChartBar, iconClass: "bg-bg-secondary text-ink-secondary" },
  conversation: { icon: IconMessageQuestion, iconClass: "bg-ai-bg text-ai" },
};

export function RecentActivityFeed({
  projectId,
  insights,
  generatedAt,
  hasData = true,
}: {
  projectId: string;
  insights: Array<ProjectInsightCard & { category: string }>;
  generatedAt?: string;
  hasData?: boolean;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: recentConversationsKey(projectId),
    queryFn: () =>
      getRecentProjectConversations(projectId, RECENT_CONVERSATIONS_LIMIT),
    enabled: Boolean(projectId),
  });

  const rows = useMemo<FeedRow[]>(() => {
    const insightRows: FeedRow[] = insights.map((insight) => ({
      key: `insight-${insight.id}`,
      kind: (insight.category as InsightKind) ?? "analysis",
      title: insight.title,
      detail: `${insightCategory(insight.category)} flagged in Project Insights`,
      ts: insight.executedAt ?? generatedAt ?? new Date().toISOString(),
      href: `/projects/${projectId}/insight`,
    }));

    const conversationRows: FeedRow[] = (data?.items ?? []).map((item) => ({
      key: `conversation-${item.conversation_id}-${item.turn_id}`,
      kind: "conversation",
      title: item.question_preview,
      detail: item.result_preview,
      ts: item.completed_at,
      href: conversationHref(projectId, item),
    }));

    return [...insightRows, ...conversationRows]
      .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime())
      .slice(0, FEED_LIMIT);
  }, [insights, data, generatedAt, projectId]);

  const empty = !isLoading && !isError && rows.length === 0;

  return (
    <Card className="flex flex-col">
      <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
        <span className="text-h3 text-ink-primary">Recent activity</span>
        <div className="flex items-center gap-3 text-[12px] font-medium text-brand-700">
          <Link href={`/projects/${projectId}/insight`} className="hover:underline">
            View insights
          </Link>
          <Link
            href={buildAiAssistantHref({ projectId, origin: "project-overview" })}
            className="hover:underline"
          >
            View conversations
          </Link>
        </div>
      </div>
      <div className="p-2">
        {!hasData ? (
          <div className="px-2 py-8 text-center text-small text-ink-tertiary">
            No project data yet. Connect a data source or upload documents to
            generate insights.
          </div>
        ) : empty ? (
          <div className="px-2 py-8 text-center text-small text-ink-tertiary">
            No insights or conversations yet. Ask anything above to get
            started.
          </div>
        ) : (
          <ul className="divide-y divide-line-tertiary">
            {rows.map((row) => {
              const { icon: Icon, iconClass } = ICON_STYLE[row.kind];
              return (
                <li key={row.key}>
                  <Link
                    href={row.href}
                    className="group flex items-start gap-3 rounded-md px-2 py-3 hover:bg-bg-secondary"
                  >
                    <span
                      className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${iconClass}`}
                    >
                      <Icon size={15} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] font-semibold text-ink-primary group-hover:text-brand-700">
                        {row.kind === "conversation" ? `"${row.title}"` : row.title}
                      </span>
                      <span className="mt-0.5 block truncate text-small text-ink-tertiary">
                        {row.detail}
                      </span>
                    </span>
                    <span className="shrink-0 pt-0.5 text-small text-ink-tertiary">
                      {timeAgo(row.ts)}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}
