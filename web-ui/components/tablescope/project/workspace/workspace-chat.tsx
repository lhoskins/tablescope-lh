"use client";

import { useEffect, useRef, useState } from "react";
import { IconSparkles } from "@tabler/icons-react";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import { AskAnythingComposer } from "@/components/ai/ask-anything-composer";
import { useWorkspaceChat } from "./use-workspace-chat";
import { WorkspaceSnippetList } from "./workspace-snippet-list";
import { PaneEmptyState } from "./pane-empty-state";
import type { WorkspaceSnippet } from "./workspace-snippet-storage";
import type { ConversationTurn } from "@/lib/api/conversational-analytics";
import type { WorkspaceCard } from "@/lib/api/workspaces";

/**
 * The chat body used by the Chat pane and by each pane's chat drawer.
 *
 * Same bubbles, composer and voice input as the rest of the app, so a
 * conversation here behaves like one anywhere else; only the grounding and the
 * history shown differ (see `useWorkspaceChat`).
 */
export function WorkspaceChat({
  projectId,
  cards,
  focusedCard,
  resume,
  emptyHint,
  snippets,
  onRemoveSnippet,
  onClearSnippets,
  onTurnsChange,
  hidePinned,
}: {
  projectId: string;
  cards: WorkspaceCard[];
  /** The card in the Preview pane, named to the assistant as the user's focus. */
  focusedCard?: WorkspaceCard | null;
  /** Load the project's existing workspace thread on mount. */
  resume: boolean;
  emptyHint?: React.ReactNode;
  /** Pinned excerpts: shown above the composer and quoted to the assistant. */
  snippets?: WorkspaceSnippet[];
  onRemoveSnippet?: (id: number) => void;
  onClearSnippets?: () => void;
  /** Lets a drawer's ↗ button lift this conversation's last exchange. */
  onTurnsChange?: (turns: ConversationTurn[]) => void;
  /** Hides the Pinned Context panel without discarding what's pinned or
   *  changing what's sent to the assistant -- a display toggle, not a clear. */
  hidePinned?: boolean;
}) {
  const { turns, pendingMessage, busy, error, send, cancel } = useWorkspaceChat({
    projectId,
    cards,
    focusedCard,
    snippets,
    resume,
  });
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [turns, busy]);

  // Publish upward so the pane's ↗ can capture the latest exchange without
  // this component owning what "send to the Chat pane" means.
  useEffect(() => {
    onTurnsChange?.(turns);
  }, [turns, onTurnsChange]);

  const projectIdNum = Number(projectId);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Above the transcript, not above the composer: what the conversation is
          anchored to should be the first thing read on entering the pane, and
          it stays put while messages scroll underneath. */}
      {snippets && onRemoveSnippet && !hidePinned && (
        <WorkspaceSnippetList
          snippets={snippets}
          onRemove={onRemoveSnippet}
          onClear={onClearSnippets}
          storageKey="chat"
        />
      )}

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {turns.length === 0 && !pendingMessage && (
          <PaneEmptyState className="-mt-3 px-0">
            {emptyHint ?? <GroundingHint cards={cards} focusedCard={focusedCard} />}
          </PaneEmptyState>
        )}
        {turns.map((turn, index) => (
          <TurnBubble
            key={turn.id}
            turn={turn}
            isLast={index === turns.length - 1}
            onFollowUp={(text) => void send(text)}
          />
        ))}
        {pendingMessage && (
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-lg bg-brand px-3 py-2 text-[13px] leading-relaxed text-brand-fg">
              {pendingMessage}
            </div>
          </div>
        )}
        {busy && (
          <div className="flex gap-2">
            <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
              <IconSparkles size={13} />
            </div>
            <div className="max-w-[85%] rounded-lg border border-line-tertiary bg-bg-secondary px-3 py-2 text-[13px] text-ink-tertiary">
              Thinking…
            </div>
          </div>
        )}
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger"
          >
            {error}
          </div>
        )}
      </div>

      {/* Pinned outside the scroll region so the input never drifts away. */}
      <div className="shrink-0 border-t border-line-tertiary px-2 py-2">
        <AskAnythingComposer
          value={input}
          onChange={setInput}
          onSubmit={(value) => {
            void send(value);
            setInput("");
          }}
          onCancel={cancel}
          busy={busy}
          voiceEnabled
          placeholder="Ask about this workspace…"
          ariaLabel="Ask about this workspace"
          submitAriaLabel="Send"
          cancelAriaLabel="Stop"
          projectId={Number.isFinite(projectIdNum) ? projectIdNum : undefined}
        />
      </div>
    </div>
  );
}

/** Tells the user what the assistant can actually see, so an ungrounded chat
 *  in an empty workspace isn't mistaken for a broken one. */
function GroundingHint({
  cards,
  focusedCard,
}: {
  cards: WorkspaceCard[];
  focusedCard?: WorkspaceCard | null;
}) {
  if (cards.length === 0) {
    return (
      <>
        Select text from other panes to give context to the Chat pane.
      </>
    );
  }
  const names = cards.map((card) => card.label ?? card.resource_type).join(", ");
  return (
    <>
      Grounded on {cards.length === 1 ? "" : `${cards.length} items: `}
      <span className="text-ink-secondary">{names}</span>.
      {focusedCard && (
        <>
          {" "}
          Focused on{" "}
          <span className="font-medium text-ink-secondary">
            {focusedCard.label ?? focusedCard.resource_type}
          </span>
          .
        </>
      )}
    </>
  );
}
