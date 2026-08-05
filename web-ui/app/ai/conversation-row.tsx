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
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";import { MenuItem } from "./menu-item";



export function ConversationRow({
  conversation,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  conversation: ConversationSummary;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conversation.title);

  const startRename = () => {
    setDraft(conversation.title);
    setEditing(true);
    setMenuOpen(false);
  };

  const commitRename = () => {
    const next = draft.trim();
    if (next && next !== conversation.title) onRename(next);
    setEditing(false);
  };

  return (
    <div
      className={cn(
        "group relative flex items-center rounded-md py-2 pl-2 pr-1 text-[13px]",
        active
          ? "bg-brand-50 text-brand-700"
          : "text-ink-secondary hover:bg-bg-primary",
      )}
      onContextMenu={(e) => {
        e.preventDefault();
        setMenuOpen(true);
      }}
    >
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") setEditing(false);
          }}
          className="min-w-0 flex-1 rounded border border-line-secondary bg-bg-primary px-1.5 py-0.5 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
        />
      ) : (
        <button
          type="button"
          onClick={onSelect}
          className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap scrollbar-none text-left"
          title={conversation.title}
        >
          {conversation.title}
        </button>
      )}
      {!editing && (
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="Conversation actions"
          className={cn(
            "shrink-0 rounded text-ink-tertiary hover:text-ink-secondary",
            menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100",
          )}
        >
          <IconDots size={15} />
        </button>
      )}
      {menuOpen && (
        <>
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setMenuOpen(false)}
          />
          <div className="absolute right-1 top-8 z-50 w-36 overflow-hidden rounded-md border border-line-tertiary bg-bg-primary py-1 shadow-lg">
            <MenuItem
              icon={<IconPencil size={14} />}
              label="Rename"
              onClick={startRename}
            />
            <MenuItem
              icon={<IconTrash size={14} />}
              label="Delete"
              danger
              onClick={() => {
                onDelete();
                setMenuOpen(false);
              }}
            />
          </div>
        </>
      )}
    </div>
  );
}