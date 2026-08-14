"use client";

import { useEffect } from "react";
import { IconX } from "@tabler/icons-react";
import { ConversationListPanel } from "./conversation-list-panel";
import type { ConversationSummary } from "@/lib/api/conversational-analytics";

export function MobileConversationDrawer({
  open,
  onClose,
  conversations,
  activeId,
  onNew,
  onSelect,
  onRename,
  onDelete,
}: {
  open: boolean;
  onClose: () => void;
  conversations: ConversationSummary[];
  activeId: number | null;
  onNew: () => void;
  onSelect: (id: number) => void;
  onRename: (id: number, title: string) => void;
  onDelete: (id: number) => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/40 lg:hidden"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Conversations"
        className="fixed inset-y-0 left-0 z-50 flex w-3/4 max-w-[280px] flex-col border-r border-line-tertiary bg-bg-secondary shadow-xl lg:hidden"
      >
        <div className="flex h-14 shrink-0 items-center justify-end border-b border-line-tertiary px-3">
          <button
            type="button"
            onClick={onClose}
            aria-label="Close conversations"
            className="flex h-10 w-10 items-center justify-center rounded-md text-ink-secondary hover:bg-bg-secondary"
          >
            <IconX size={20} />
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <ConversationListPanel
            conversations={conversations}
            activeId={activeId}
            onNew={onNew}
            onSelect={onSelect}
            onRename={onRename}
            onDelete={onDelete}
          />
        </div>
      </div>
    </>
  );
}
