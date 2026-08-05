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

export const FALLBACK_TENANT: TenantSummary = {
  name: "Tablescope",
  slug: "",
  initials: "TS",
};