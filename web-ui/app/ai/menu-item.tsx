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


export function MenuItem({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-bg-secondary",
        danger ? "text-danger" : "text-ink-secondary",
      )}
    >
      {icon}
      {label}
    </button>
  );
}