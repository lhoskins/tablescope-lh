"use client";

import { useEffect, useState } from "react";
import { IconPlus, IconSparkles, IconTrash } from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import {
  loadDraftActions,
  nextDraftActionId,
  saveDraftActions,
  type DraftAction,
} from "./workspace-actions-storage";

/**
 * The step before Project Actions: jot down what you want done while you're
 * still looking at the data, and let the assistant propose more from a
 * description of what you're trying to do. Nothing here reaches the project's
 * action board until it's promoted, so it stays a scratchpad.
 */
export function WorkspaceActionsPane({
  projectId,
  workspaceId,
  onSuggest,
  suggesting = false,
}: {
  projectId: string;
  workspaceId: number | null;
  /** Ask the assistant for actions given what the user described. Wired to the
   *  workspace chat; until that lands the button stays disabled. */
  onSuggest?: (context: string) => void;
  suggesting?: boolean;
}) {
  const [actions, setActions] = useState<DraftAction[]>([]);
  const [draft, setDraft] = useState("");
  const [context, setContext] = useState("");

  useEffect(() => {
    setActions(workspaceId == null ? [] : loadDraftActions(projectId, workspaceId));
  }, [projectId, workspaceId]);

  const persist = (next: DraftAction[]) => {
    setActions(next);
    if (workspaceId != null) saveDraftActions(projectId, workspaceId, next);
  };

  const add = () => {
    const text = draft.trim();
    if (!text || workspaceId == null) return;
    persist([
      ...actions,
      {
        id: nextDraftActionId(actions),
        projectId,
        workspaceId,
        text,
        done: false,
        createdAt: new Date().toISOString(),
      },
    ]);
    setDraft("");
  };

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
          onClick={() => onSuggest?.(context.trim())}
          disabled={!onSuggest || !context.trim() || suggesting}
          title={
            onSuggest
              ? "Ask the assistant for actions based on this workspace"
              : "Available once the workspace chat is wired up"
          }
          className="flex h-8 w-full items-center justify-center gap-1.5 rounded-md border border-line-secondary bg-bg-primary text-[12px] font-medium text-ink-secondary hover:bg-brand-50 hover:text-brand-500 disabled:opacity-40"
        >
          <IconSparkles size={14} />
          {suggesting ? "Thinking…" : "Suggest actions"}
        </button>
      </div>
    </div>
  );
}
