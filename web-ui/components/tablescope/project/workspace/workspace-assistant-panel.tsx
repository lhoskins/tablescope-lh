"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  IconChevronRight,
  IconChevronLeft,
  IconSparkles,
  IconPlus,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import { AskAnythingComposer } from "@/components/ai/ask-anything-composer";
import {
  getConversation,
  listConversations,
  submitCanonicalTurn,
  type Conversation,
} from "@/lib/api/conversational-analytics";
import {
  ASSISTANT_MAX_WIDTH,
  ASSISTANT_MIN_WIDTH,
  clampAssistantWidth,
  loadAssistantCollapsed,
  loadAssistantWidth,
  saveAssistantCollapsed,
  saveAssistantWidth,
} from "./workspace-assistant-storage";
import type { WorkspaceTab } from "./workspace-tabs-storage";
import type { WorkspaceCard } from "@/lib/api/workspaces";

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function WorkspaceAssistantPanel({
  projectId,
  activeItem,
  surface = "project_workspace",
  contextLabel,
  workspaceCards,
  defaultOpen = false,
}: {
  projectId?: string;
  activeItem?: WorkspaceTab | null;
  surface?: "business_insights" | "project_insights" | "project_workspace";
  contextLabel?: string;
  /** Cards of the active named workspace. When set, the assistant grounds on
   *  every card instead of the single active tab. */
  workspaceCards?: WorkspaceCard[] | null;
  /** Open the panel when nothing has been persisted yet. Only the Workspace
   *  page opts in; elsewhere the panel stays collapsed by default. */
  defaultOpen?: boolean;
}) {
  const projectIdNum = Number(projectId);
  const hasProject = projectId != null && projectId !== "" && Number.isFinite(projectIdNum);
  const [collapsed, setCollapsed] = useState(true);
  const [width, setWidth] = useState(ASSISTANT_MIN_WIDTH);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const resizingRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setCollapsed(loadAssistantCollapsed(!defaultOpen));
    setWidth(loadAssistantWidth());
  }, [defaultOpen]);

  const groundedCards = (workspaceCards ?? []).filter(
    (card) => Number.isFinite(Number(card.resource_id)),
  );
  const groundedLabel =
    groundedCards.length > 0
      ? groundedCards.map((c) => c.label ?? c.resource_type).join(", ")
      : (activeItem?.label ?? contextLabel);

  // Resume conversation history only once the panel is actually opened, and
  // only once per mount -- this panel is present on every project page, so
  // fetching eagerly on every navigation (most of which never open it) added
  // an extra request/DB round trip to pages that have nothing to do with the
  // assistant, which is exactly the kind of avoidable load the docked panel
  // was meant to avoid.
  const hasResumedRef = useRef(false);
  useEffect(() => {
    if (collapsed || hasResumedRef.current) return;
    hasResumedRef.current = true;
    let cancelled = false;
    async function resume() {
      try {
        const list = await listConversations(hasProject ? projectIdNum : undefined);
        const workspace = list.find(
          (c) => c.surface === surface && (hasProject || c.project_id == null),
        );
        if (!workspace || cancelled) return;
        const full = await getConversation(workspace.id);
        if (!cancelled) setConversation(full);
      } catch {
        // No prior workspace conversation to resume -- start fresh silently.
      }
    }
    void resume();
    return () => {
      cancelled = true;
    };
  }, [collapsed, hasProject, projectIdNum, surface]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [conversation?.turns, busy]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      saveAssistantCollapsed(next);
      return next;
    });
  };

  const onResizeStart = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();
      resizingRef.current = true;
      const startX = event.clientX;
      const startWidth = width;

      const onMove = (moveEvent: MouseEvent) => {
        if (!resizingRef.current) return;
        // The handle sits on the panel's left edge, so dragging left (negative
        // delta) should widen the panel.
        const delta = startX - moveEvent.clientX;
        setWidth(clampAssistantWidth(startWidth + delta));
      };
      const onUp = () => {
        resizingRef.current = false;
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        setWidth((current) => {
          saveAssistantWidth(current);
          return current;
        });
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [width],
  );

  async function send(raw: string) {
    const message = raw.trim();
    if (!message || busy) return;
    setPendingMessage(message);
    setInput("");
    setBusy(true);
    setError(null);
    const controller = new AbortController();
    abortControllerRef.current = controller;
    try {
      const result = await submitCanonicalTurn(
        {
          surface,
          project_id: hasProject ? projectIdNum : undefined,
          message,
          client_request_id: newRequestId(),
          active_resource_type: groundedCards.length > 0 ? undefined : activeItem?.type,
          active_resource_id: groundedCards.length > 0 ? undefined : activeItem?.numericId,
          active_resources:
            groundedCards.length > 0
              ? groundedCards.map((card) => ({
                  resource_type: card.resource_type,
                  resource_id: Number(card.resource_id),
                }))
              : undefined,
        },
        controller.signal,
      );
      setConversation((prev) => {
        if (!prev || prev.id !== result.conversation_id) {
          return {
            id: result.conversation_id,
            project_id: result.project_id,
            surface: result.surface,
            title: contextLabel ?? "Workspace",
            status: "active",
            active_datasource_id: null,
            canonical_key: null,
            merged_into_conversation_id: null,
            turns: [result.turn],
            updated_at: new Date().toISOString(),
          };
        }
        return { ...prev, turns: [...prev.turns, result.turn], updated_at: new Date().toISOString() };
      });
    } catch (err) {
      // A user-initiated stop is not a failure -- the request is simply
      // abandoned client-side, the same as every other onCancel usage of
      // AskAnythingComposer in this app.
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof Error ? err.message : "Something went wrong.");
      }
    } finally {
      abortControllerRef.current = null;
      setPendingMessage(null);
      setBusy(false);
    }
  }

  function cancelSend() {
    abortControllerRef.current?.abort();
  }

  function startNew() {
    setConversation(null);
    setInput("");
    setError(null);
  }

  if (collapsed) {
    return (
      <div className="flex w-[54px] shrink-0 flex-col items-center gap-3 border-l border-line-tertiary bg-bg-primary py-3">
        <button
          type="button"
          onClick={toggleCollapsed}
          title="Open AI Assistant"
          aria-label="Open AI Assistant"
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-500 hover:bg-brand-100"
        >
          <IconSparkles size={16} />
        </button>
        <button
          type="button"
          onClick={toggleCollapsed}
          title="Expand"
          aria-label="Expand AI Assistant panel"
          className="flex h-7 w-7 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
        >
          <IconChevronLeft size={14} />
        </button>
      </div>
    );
  }

  const pendingQuestion = busy ? pendingMessage : null;

  return (
    <div
      className="relative flex shrink-0 flex-col border-l border-line-tertiary bg-bg-primary"
      style={{ width, minWidth: ASSISTANT_MIN_WIDTH, maxWidth: ASSISTANT_MAX_WIDTH }}
    >
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
      <div
        onMouseDown={onResizeStart}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize AI Assistant panel"
        className="absolute left-0 top-0 h-full w-1.5 -translate-x-1/2 cursor-col-resize"
      />
      <div className="flex items-center justify-between gap-2 border-b border-line-tertiary px-3 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-50 text-brand-500">
            <IconSparkles size={14} />
          </div>
          <div>
            <p className="text-[13px] font-medium text-ink-primary">AI Assistant</p>
            {groundedLabel && (
              <p className="max-w-[14rem] truncate text-caption text-ink-tertiary">
                Grounded on: {groundedLabel}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" title="New chat" aria-label="New chat" onClick={startNew}>
            <IconPlus size={14} />
          </Button>
          <button
            type="button"
            onClick={toggleCollapsed}
            title="Collapse"
            aria-label="Collapse AI Assistant panel"
            className="flex h-7 w-7 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
          >
            <IconChevronRight size={14} />
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-3 py-3">
        {(!conversation || conversation.turns.length === 0) && !pendingQuestion && (
          <p className="text-[13px] text-ink-tertiary">
            Ask about {groundedLabel ? `"${groundedLabel}"` : "this project"} or anything else in
            this workspace.
          </p>
        )}
        {conversation?.turns.map((t, i) => (
          <TurnBubble
            key={t.id}
            turn={t}
            isLast={i === conversation.turns.length - 1}
            onFollowUp={(text) => void send(text)}
          />
        ))}
        {pendingQuestion && (
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-lg bg-brand px-3 py-2 text-[13px] leading-relaxed text-brand-fg">
              {pendingQuestion}
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
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">
            {error}
          </div>
        )}
      </div>

      <div className="border-t border-line-tertiary px-3 py-2">
        <AskAnythingComposer
          value={input}
          onChange={setInput}
          onSubmit={(v) => void send(v)}
          onCancel={cancelSend}
          busy={busy}
          voiceEnabled
          placeholder="Ask anything…"
          ariaLabel="Ask the AI Assistant"
          submitAriaLabel="Send"
          cancelAriaLabel="Stop"
          projectId={hasProject ? projectIdNum : undefined}
        />
      </div>
    </div>
  );
}
