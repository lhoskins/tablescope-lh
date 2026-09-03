"use client";

import { useEffect, useState } from "react";
import { IconDots, IconPencil, IconTrash } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import type { ConversationSummary } from "@/lib/api/conversational-analytics";
import { MenuItem } from "./menu-item";

export interface ConversationTimestamp {
  compact: string;
  full: string;
}

export function formatConversationTimestamp(value: string): ConversationTimestamp | null {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;

  return {
    compact: new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(date),
    full: new Intl.DateTimeFormat(undefined, {
      dateStyle: "full",
      timeStyle: "long",
    }).format(date),
  };
}

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
  const [timestamp, setTimestamp] = useState<ConversationTimestamp | null>(null);

  // Format after mount so the browser's locale and time zone are used without
  // creating a server/client hydration mismatch.
  useEffect(() => {
    setTimestamp(formatConversationTimestamp(conversation.updated_at));
  }, [conversation.updated_at]);

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

  const tooltip = timestamp
    ? `${conversation.title}\nLast updated ${timestamp.full}`
    : conversation.title;

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
          className="min-w-0 flex-1 text-left"
          title={tooltip}
          aria-label={
            timestamp
              ? `${conversation.title}, last updated ${timestamp.full}`
              : conversation.title
          }
        >
          <span className="block overflow-x-auto whitespace-nowrap scrollbar-none">
            {conversation.title}
          </span>
          {timestamp && (
            <span
              className={cn(
                "mt-0.5 block text-[11px] leading-4 text-ink-tertiary transition-opacity",
                active ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
              )}
              data-testid="conversation-timestamp"
            >
              {timestamp.compact}
            </span>
          )}
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
