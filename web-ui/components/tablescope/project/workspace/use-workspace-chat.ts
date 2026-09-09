"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getConversation,
  listConversations,
  submitCanonicalTurn,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";
import type { WorkspaceCard } from "@/lib/api/workspaces";
import type { WorkspaceSnippet } from "./workspace-snippet-storage";

const SURFACE = "project_workspace" as const;

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * One workspace chat, however it is surfaced.
 *
 * Everything in a project's workspace -- the Chat pane and each pane's chat
 * drawer -- talks to the same canonical thread. That is a backend fact, not a
 * choice here: `canonical_scope_key` resolves to `project_workspace:{id}`, so
 * every turn appends to one durable conversation per project. The difference
 * between the surfaces is therefore what they *show* and what they ground on,
 * never a separate memory:
 *
 * - `resume: true` (the Chat pane) loads the whole thread on mount.
 * - `resume: false` (a drawer) starts empty and shows only the turns asked
 *   there, while still writing to the shared thread. The drawer's ↗ button
 *   reveals the Chat pane, where the same turns are already waiting.
 *
 * Grounding: every card in the workspace goes in `active_resources`, and
 * `focusedCard` names the one the user is reading. Both are sent -- the set for
 * cross-referencing, the focus so "what should I fix first?" is understood to
 * be about the open document rather than any of the five items.
 */
export function useWorkspaceChat({
  projectId,
  cards,
  focusedCard,
  snippets,
  resume,
}: {
  projectId: string;
  cards: WorkspaceCard[];
  focusedCard?: WorkspaceCard | null;
  /** Passages the user pinned; quoted to the model with every question. */
  snippets?: WorkspaceSnippet[];
  resume: boolean;
}) {
  const projectIdNum = Number(projectId);
  const hasProject = projectId !== "" && Number.isFinite(projectIdNum);

  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const conversationIdRef = useRef<number | null>(null);

  const hasResumedRef = useRef(false);
  useEffect(() => {
    if (!resume || !hasProject || hasResumedRef.current) return;
    hasResumedRef.current = true;
    let cancelled = false;
    async function load() {
      try {
        const list = await listConversations(projectIdNum);
        const thread = list.find((c) => c.surface === SURFACE);
        if (!thread || cancelled) return;
        const full = await getConversation(thread.id);
        if (cancelled) return;
        conversationIdRef.current = full.id;
        setTurns(full.turns);
      } catch {
        // Nothing to resume -- start fresh rather than showing an error for a
        // conversation the user may never have had.
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [hasProject, projectIdNum, resume]);

  // Only numeric ids resolve server-side: the backend looks each one up by
  // primary key, so a non-numeric id would be silently dropped from grounding.
  const groundable = cards.filter((card) => Number.isFinite(Number(card.resource_id)));

  const send = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || busy) return;
      setPendingMessage(message);
      setBusy(true);
      setError(null);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const result = await submitCanonicalTurn(
          {
            surface: SURFACE,
            project_id: hasProject ? projectIdNum : undefined,
            message,
            client_request_id: newRequestId(),
            active_resources: groundable.map((card) => ({
              resource_type: card.resource_type,
              resource_id: Number(card.resource_id),
            })),
            focused_resource:
              focusedCard && Number.isFinite(Number(focusedCard.resource_id))
                ? {
                    resource_type: focusedCard.resource_type,
                    resource_id: Number(focusedCard.resource_id),
                  }
                : undefined,
            // Images can't be quoted into a text prompt, so only textual
            // excerpts travel; the picture stays a visual note for the user.
            context_snippets: (snippets ?? [])
              .filter((s) => !s.image && s.text.trim())
              .map((s) => ({ label: s.label, text: s.text })),
          },
          controller.signal,
        );
        conversationIdRef.current = result.conversation_id;
        setTurns((prev) => [...prev, result.turn]);
      } catch (err) {
        // A user-initiated stop is not a failure: the request is abandoned
        // client-side, matching every other AskAnythingComposer cancel here.
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          setError(err instanceof Error ? err.message : "Something went wrong.");
        }
      } finally {
        abortRef.current = null;
        setPendingMessage(null);
        setBusy(false);
      }
    },
    [busy, focusedCard, groundable, hasProject, projectIdNum, snippets],
  );

  const cancel = useCallback(() => abortRef.current?.abort(), []);

  const clear = useCallback(() => {
    // Local only. The turns stay in the project's canonical thread; this just
    // resets what this surface is showing.
    setTurns([]);
    setError(null);
  }, []);

  return { turns, pendingMessage, busy, error, send, cancel, clear, groundable };
}
