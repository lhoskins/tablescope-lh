"use client";

import { useEffect, useRef, useState } from "react";
import { IconPlus, IconSparkles, IconTrash } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { useWorkspaceChat } from "./use-workspace-chat";
import type { WorkspaceCard } from "@/lib/api/workspaces";
import {
  loadDraftActions,
  nextDraftActionId,
  saveDraftActions,
  type DraftAction,
} from "./workspace-actions-storage";

/**
 * Pull individual actions out of an assistant reply.
 *
 * The model is asked for one action per line, but replies arrive with bullets,
 * numbering, bold markers and the occasional "Here are some actions:" preamble.
 * Rather than trust the format, take only lines that look like list items and
 * strip their decoration; a reply that ignores the format yields nothing and
 * leaves the user's own typed actions untouched.
 */
export function parseSuggestedActions(message: string | null): string[] {
  if (!message) return [];
  return message
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => /^([-*•]|\d+[.)])\s+/.test(line))
    .map((line) =>
      line
        .replace(/^([-*•]|\d+[.)])\s+/, "")
        // Markdown emphasis and code spans appear mid-sentence, not just at the
        // ends -- an anchored strip left backticks around identifiers intact.
        .replace(/\*\*/g, "")
        .replace(/`/g, "")
        .trim(),
    )
    .filter((line) => line.length > 0 && line.length <= 300)
    .slice(0, 10);
}

/**
 * The step before Project Actions: jot down what you want done while you're
 * still looking at the data, and let the assistant propose more from a
 * description of what you're trying to do. Nothing here reaches the project's
 * action board until it's promoted, so it stays a scratchpad.
 */
export function WorkspaceActionsPane({
  projectId,
  workspaceId,
  cards,
  focusedCard,
}: {
  projectId: string;
  workspaceId: number | null;
  /** Grounding for suggestions: the workspace's cards, and the one being read. */
  cards: WorkspaceCard[];
  focusedCard?: WorkspaceCard | null;
}) {
  const [actions, setActions] = useState<DraftAction[]>([]);
  const [draft, setDraft] = useState("");
  const [context, setContext] = useState("");
  const { send, busy, turns, error } = useWorkspaceChat({
    projectId,
    cards,
    focusedCard,
    resume: false,
  });
  // Turns arriving from a suggestion request become checkable draft actions.
  const consumedTurns = useRef(0);

  useEffect(() => {
    setActions(workspaceId == null ? [] : loadDraftActions(projectId, workspaceId));
  }, [projectId, workspaceId]);

  const persist = (next: DraftAction[]) => {
    setActions(next);
    if (workspaceId != null) saveDraftActions(projectId, workspaceId, next);
  };

  const appendActions = (texts: string[], suggested: boolean) => {
    if (workspaceId == null || texts.length === 0) return;
    let nextId = nextDraftActionId(actions);
    persist([
      ...actions,
      ...texts.map((text) => ({
        id: nextId++,
        projectId,
        workspaceId,
        text,
        suggested: suggested || undefined,
        done: false,
        createdAt: new Date().toISOString(),
      })),
    ]);
  };

  const add = () => {
    const text = draft.trim();
    if (!text) return;
    appendActions([text], false);
    setDraft("");
  };

  const suggest = () => {
    const situation = context.trim();
    if (!situation || busy) return;
    // Asked as a question rather than an instruction, and grounded on the
    // workspace's cards by the shared chat hook.
    void send(
      `${situation}\n\nBased on the items open in this workspace, what are the ` +
        "most useful next actions? Reply as a short list, one action per line.",
    );
  };

  // Turn the assistant's reply into draft actions the user can tick off.
  useEffect(() => {
    if (turns.length <= consumedTurns.current) return;
    const latest = turns[turns.length - 1];
    consumedTurns.current = turns.length;
    const suggestions = parseSuggestedActions(latest.assistant_message);
    if (suggestions.length > 0) {
      appendActions(suggestions, true);
      setContext("");
    }
    // `appendActions` closes over `actions`, which this effect also updates via
    // persist -- depending on it would re-run and duplicate the suggestions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turns]);

  if (workspaceId == null) {
    return (
      <p className="flex flex-1 items-center justify-center px-5 text-center text-[12px] text-ink-tertiary">
        Create a workspace to start capturing actions.
      </p>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {actions.length === 0 && (
          <p className="py-4 text-center text-[12px] leading-relaxed text-ink-tertiary">
            No actions yet. Type what you want done,
            <br />
            or describe the situation and ask for suggestions.
          </p>
        )}
        {actions.map((action) => (
          <div
            key={action.id}
            className="group flex items-start gap-2 rounded-md border border-line-tertiary bg-bg-primary px-2 py-1.5"
          >
            <input
              type="checkbox"
              checked={action.done}
              onChange={() =>
                persist(
                  actions.map((a) =>
                    a.id === action.id ? { ...a, done: !a.done } : a,
                  ),
                )
              }
              aria-label={`Mark "${action.text}" done`}
              className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded border-line-secondary text-brand focus:ring-brand"
            />
            <span
              className={cn(
                "min-w-0 flex-1 break-words text-[12px] leading-snug",
                action.done ? "text-ink-tertiary line-through" : "text-ink-primary",
              )}
            >
              {action.text}
              {action.suggested && (
                <span className="ml-1 align-middle text-caption font-semibold uppercase tracking-wide text-brand-500">
                  AI
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => persist(actions.filter((a) => a.id !== action.id))}
              aria-label={`Remove "${action.text}"`}
              className="shrink-0 rounded p-0.5 text-ink-tertiary opacity-0 hover:text-danger group-hover:opacity-100"
            >
              <IconTrash size={13} />
            </button>
          </div>
        ))}
      </div>

      <div className="shrink-0 space-y-2 border-t border-line-tertiary px-3 py-2">
        <div className="flex items-end gap-1.5">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }}
            placeholder="Add an action…"
            aria-label="Add an action"
            className="h-8 min-w-0 flex-1 rounded-md border border-line-secondary bg-bg-primary px-2 text-[12px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={add}
            disabled={!draft.trim()}
            aria-label="Add action"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-line-secondary bg-bg-primary text-ink-secondary hover:bg-brand-50 hover:text-brand-500 disabled:opacity-40"
          >
            <IconPlus size={14} />
          </button>
        </div>

        <textarea
          value={context}
          onChange={(event) => setContext(event.target.value)}
          rows={2}
          placeholder="What are you looking at, and what are you trying to do?"
          aria-label="Describe what you are trying to do"
          className="w-full resize-none rounded-md border border-line-secondary bg-bg-primary px-2 py-1.5 text-[12px] leading-snug text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
        />
        <button
          type="button"
          onClick={suggest}
          disabled={!context.trim() || busy}
          title="Ask the assistant for actions based on this workspace"
          className="flex h-8 w-full items-center justify-center gap-1.5 rounded-md border border-line-secondary bg-bg-primary text-[12px] font-medium text-ink-secondary hover:bg-brand-50 hover:text-brand-500 disabled:opacity-40"
        >
          <IconSparkles size={14} />
          {busy ? "Thinking…" : "Suggest actions"}
        </button>
        {error && (
          <p role="alert" className="text-[11px] text-danger">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
