"use client";

import { IconPlus } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { ConversationRow } from "./conversation-row";
import type { ConversationSummary } from "@/lib/api/conversational-analytics";

export function ConversationListPanel({
  conversations,
  activeId,
  onNew,
  onSelect,
  onRename,
  onDelete,
}: {
  conversations: ConversationSummary[];
  activeId: number | null;
  onNew: () => void;
  onSelect: (id: number) => void;
  onRename: (id: number, title: string) => void;
  onDelete: (id: number) => void;
}) {
  return (
    <>
      <div className="border-b border-line-tertiary p-2.5">
        <Button
          variant="secondary"
          className="w-full justify-start gap-2"
          onClick={onNew}
        >
          <IconPlus size={14} />
          New chat
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {conversations.length === 0 && (
          <p className="px-2 py-4 text-small text-ink-tertiary">
            No conversations yet.
          </p>
        )}
        {conversations.map((c) => (
          <ConversationRow
            key={c.canonical_key ?? c.id}
            conversation={c}
            active={activeId === c.id}
            onSelect={() => onSelect(c.id)}
            onRename={(title) => onRename(c.id, title)}
            onDelete={() => onDelete(c.id)}
          />
        ))}
      </div>
    </>
  );
}
