"use client";


import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { IconUsers, IconLoader2 } from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { MembersDialog } from "@/components/tablescope/project/members-dialog";
import { ShareToggle } from "@/components/tablescope/project/share-toggle";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { ContextPanel, ContextSection, IsolationCard } from "@/components/tablescope/context-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import {
  AiConversationsCard,
  recentConversationsKey,
} from "@/components/tablescope/project/ai-conversations-card";
import { QuickActionsCard } from "@/components/tablescope/project/quick-actions-card";
import {
  createConversation,
  getConversation,
  submitTurn,
  type Conversation,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";
import { projectInsightApi, type ProjectInsight, type ProjectInsightCard } from "@/lib/api/project-insight";
import { timeAgo, aiStatusLabel, aiStatusTone } from "@/lib/ui/format";
import type { AiStatus, ProjectSummary } from "@/lib/ui/types";
import {
  useProjectShell,
  useProjectQueries,
  useProjectDataSources,
  useProjectDashboards,
  useProjectMembers,
  useProjectActivity,
  useProjectGraph,
  type DataSource,
} from "@/lib/ui/use-project-data";import { severityTone } from "./severity-tone";
import { insightCategory } from "./insight-category";



export function RecentInsightsCard({
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
  return (
    <Card className="flex flex-col">
      <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
        <span className="text-h3 text-ink-primary">Recent insights</span>
        <Link
          href={`/projects/${projectId}/insight`}
          className="text-[12px] font-medium text-brand-700 hover:underline"
        >
          View all
        </Link>
      </div>
      <div className="flex-1 p-2">
        {!hasData || insights.length === 0 ? (
          <div className="px-2 py-8 text-center text-small text-ink-tertiary">
            {!hasData
              ? "No project data yet. Connect a data source or upload documents to generate insights."
              : "No insights yet. Ask anything or generate insights to see findings here."}
          </div>
        ) : (
          <ul className="space-y-1">
            {insights.map((insight) => (
              <li key={insight.id}>
                <a
                  href={`/projects/${projectId}/insight`}
                  className="group flex items-start gap-2 rounded-md px-2 py-2 hover:bg-bg-secondary"
                >
                  <Badge tone={severityTone(insight.severity)} size="sm">
                    {insightCategory(insight.category)}
                  </Badge>
                  <span className="min-w-0 flex-1 text-[13px] font-medium text-ink-primary group-hover:text-brand-700">
                    {insight.title}
                  </span>
                  <span className="shrink-0 text-small text-ink-tertiary">
                    {timeAgo(insight.executedAt ?? generatedAt ?? new Date().toISOString())}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}