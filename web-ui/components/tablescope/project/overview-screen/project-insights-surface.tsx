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

export const PROJECT_INSIGHTS_SURFACE = "project_insights";