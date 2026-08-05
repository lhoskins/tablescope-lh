"use client";


import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconAlertCircle,
  IconChevronRight,
  IconHelpCircle,
  IconLoader2,
  IconSparkles,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { Button } from "@/components/ui/button";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { formatLastUpdated } from "@/lib/format-datetime";
import { HomeAiSuggestions } from "@/components/tablescope/home/ai-suggestions";
import { IntelligenceWorkspace } from "@/components/tablescope/insights/intelligence-workspace";
import { ExecutiveProjectSummary } from "@/components/tablescope/project-insight/executive-project-summary";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import { SaveInsightToDashboardModal } from "@/components/tablescope/home/save-insight-to-dashboard-modal";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";
import { createHomePin, getHomePins } from "@/lib/api/home-pins";
import { suggestInsights, type InsightCard } from "@/lib/api/home-intelligence";

import { projectInsightApi, type ProjectInsight } from "@/lib/api/project-insight";
import {
  createConversation,
  getConversation,
  submitTurn,
  type Conversation,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";
import {
  CreateActionFromInsightDialog,
  type ActionableInsight,
} from "@/components/tablescope/project-actions/create-action-from-insight-dialog";


export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary py-16 text-center">
      <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-500">
        <IconSparkles size={22} />
      </div>
      <div className="text-h2 text-ink-primary">{title}</div>
      <p className="mx-auto mt-1 max-w-md text-small text-ink-tertiary">{body}</p>
    </div>
  );
}