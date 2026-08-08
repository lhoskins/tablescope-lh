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
} from "@/lib/ui/use-project-data";


export function ProjectHeader({
  project,
  memberCount,
  aiStatus,
  onMembers,
  onToast,
}: {
  project: ProjectSummary | null;
  memberCount: number;
  aiStatus: AiStatus;
  onMembers: () => void;
  onToast: (message: string, tone?: "success" | "error" | "info") => void;
}) {
  const statusLabel = aiStatusLabel(aiStatus);
  const statusTone = aiStatusTone(aiStatus);
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-line-tertiary bg-bg-primary p-4">
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-lg font-semibold text-white"
          style={{ backgroundColor: project?.accent ?? "var(--brand-500)" }}
        >
          {(project?.name ?? "P").slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-h1 text-ink-primary">{project?.name ?? "Project"}</h1>
            <Badge tone={statusTone} title={`Project status: ${statusLabel}`}>
              {statusLabel}
            </Badge>
          </div>
          <p className="mt-0.5 text-small text-ink-tertiary">
            {project?.visibility === "shared" ? "Shared" : "Private"} project
            {memberCount > 0 && ` · ${memberCount} member${memberCount === 1 ? "" : "s"}`}
            {project?.updatedLabel && ` · Updated ${project.updatedLabel}`}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ShareToggle
          projectId={String(project?.id ?? "")}
          shared={project?.visibility === "shared"}
          onToast={onToast}
        />
        <Button variant="secondary" onClick={onMembers}>
          <IconUsers size={14} />
          Members
        </Button>
      </div>
    </header>
  );
}