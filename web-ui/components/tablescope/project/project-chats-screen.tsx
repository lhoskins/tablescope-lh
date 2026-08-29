"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IconMenu2, IconRefresh, IconSparkles } from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { AskAnythingComposer } from "@/components/ai/ask-anything-composer";
import { ConversationListPanel } from "@/app/ai/conversation-list-panel";
import { MobileConversationDrawer } from "@/app/ai/mobile-conversation-drawer";
import { TurnBubbles } from "@/app/ai/turn-bubbles";
import { UserBubble } from "@/app/ai/user-bubble";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  renameConversation,
  submitTurn,
  type Conversation,
} from "@/lib/api/conversational-analytics";

/**
 * Project-scoped Chats (`docs/ux-workspace-redesign-gap-analysis.md` §3):
 * the real AI Assistant conversation experience, not a separate chat
 * mechanism -- same `conversational-analytics` API as the global `/ai`
 * page (`listConversations`/`createConversation`/`submitTurn`), just
 * always scoped to this project. Deliberately does NOT reuse
 * `AiAssistantScreen` (`ai-assistant-screen.tsx`), which talks to the
 * separate, non-persisted `askProjectAi` endpoint -- wiring Chats to that
 * would reintroduce the exact "two disconnected chat pipelines" bug this
 * app already had and fixed once.
 */
export function ProjectChatsScreen({ projectId }: { projectId: string }) {
  const projectIdNum = Number(projectId);
  const queryClient = useQueryClient();
  const { data: conversations } = useQuery({
    queryKey: ["conversational-analytics", "conversations", { projectId: projectIdNum }],
    queryFn: () => listConversations(projectIdNum),
  });

  const [activeId, setActiveId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const { data: active } = useQuery({
    queryKey: ["conversational-analytics", "conversation", activeId],
    queryFn: () => getConversation(activeId as number),
    enabled: activeId != null,
  });
  const turns = active?.turns ?? [];

  const invalidateConvos = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: ["conversational-analytics", "conversations", { projectId: projectIdNum }],
      }),
    [queryClient, projectIdNum],
  );
  const invalidateActive = useCallback(
    (id: number) =>
      queryClient.invalidateQueries({
        queryKey: ["conversational-analytics", "conversation", id],
      }),
    [queryClient],
  );

  const sendMutation = useMutation({
    mutationFn: async (question: string): Promise<Conversation | { conversation_id: number }> => {
      const signal = abortControllerRef.current?.signal;
      if (activeId == null) {
        const convo = await createConversation(
          { project_id: projectIdNum, initial_message: question },
          signal,
        );
        setActiveId(convo.id);
        return convo;
      }
      return submitTurn(activeId, { message: question }, signal);
    },
    onSuccess: (res) => {
      const id = "conversation_id" in res ? res.conversation_id : res.id;
      invalidateActive(id);
      invalidateConvos();
    },
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      renameConversation(id, { title }),
    onSuccess: () => invalidateConvos(),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteConversation(id),
    onSuccess: (_data, id) => {
      if (activeId === id) setActiveId(null);
      invalidateConvos();
    },
  });

  const busy = sendMutation.isPending;
  const pendingQuestion = busy ? (sendMutation.variables as string) : null;

  const send = useCallback(
    (raw: string) => {
      const question = raw.trim();
      if (!question || busy) return;
      setInput("");
      abortControllerRef.current = new AbortController();
      sendMutation.mutate(question);
    },
    [busy, sendMutation],
  );

  const startNew = useCallback(() => {
    setActiveId(null);
    setInput("");
  }, []);

  const conversationList = useMemo(() => conversations ?? [], [conversations]);

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-ai-assistant"
      breadcrumbLabel="Chats"
      scrollable={false}
      showResourceTabs={false}
    >
      <div className="relative flex h-[calc(100dvh-9rem)] min-h-0 flex-col gap-0 overflow-hidden rounded-lg border border-line-tertiary lg:flex-row">
        <aside className="hidden w-[260px] shrink-0 flex-col border-r border-line-tertiary bg-bg-secondary lg:flex">
          <ConversationListPanel
            conversations={conversationList}
            activeId={activeId}
            onNew={startNew}
            onSelect={setActiveId}
            onRename={(id, title) => renameMutation.mutate({ id, title })}
            onDelete={(id) => setConfirmDeleteId(id)}
          />
        </aside>

        <MobileConversationDrawer
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          conversations={conversationList}
          activeId={activeId}
          onNew={() => {
            startNew();
            setMobileOpen(false);
          }}
          onSelect={(id) => {
            setActiveId(id);
            setMobileOpen(false);
          }}
          onRename={(id, title) => renameMutation.mutate({ id, title })}
          onDelete={(id) => setConfirmDeleteId(id)}
        />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-bg-primary">
          <div className="flex items-center justify-end border-b border-line-tertiary px-4 py-2 lg:hidden">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              aria-label="Open conversations"
              className="inline-flex h-9 items-center gap-2 rounded-md px-3 text-[12px] font-medium text-ink-secondary hover:bg-bg-secondary"
            >
              <IconMenu2 size={18} />
              Conversations
            </button>
          </div>

          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {turns.length === 0 && !pendingQuestion ? (
              <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center text-center">
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-500">
                  <IconSparkles size={24} />
                </div>
                <h2 className="text-h2 text-ink-primary">Ask about this project</h2>
                <p className="mt-1.5 text-small text-ink-tertiary">
                  Every conversation here is scoped to this project&apos;s tables,
                  documents, and dashboards.
                </p>
              </div>
            ) : (
              <div className="mx-auto max-w-3xl space-y-5">
                {turns.map((t) => (
                  <div key={t.id} id={`turn-${t.id}`}>
                    <TurnBubbles turn={t} />
                  </div>
                ))}
                {pendingQuestion && <UserBubble content={pendingQuestion} />}
                {busy && (
                  <div className="flex items-start gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
                      <IconSparkles size={16} />
                    </div>
                    <div className="rounded-xl bg-bg-secondary px-4 py-3 text-[13px] text-ink-tertiary">
                      <span className="inline-flex gap-1">
                        <span className="animate-pulse">●</span>
                        <span className="animate-pulse delay-100">●</span>
                        <span className="animate-pulse delay-200">●</span>
                      </span>
                    </div>
                  </div>
                )}
                {sendMutation.isError && !busy && (
                  <div className="flex items-center justify-between gap-3 rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-[13px] text-danger">
                    <span>
                      {(sendMutation.error as Error)?.message ?? "Something went wrong."}
                    </span>
                    <button
                      type="button"
                      onClick={() => sendMutation.variables && sendMutation.mutate(sendMutation.variables)}
                      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-danger/40 px-2 py-1 text-[12px] font-medium hover:bg-danger/10"
                    >
                      <IconRefresh size={13} />
                      Retry
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="border-t border-line-tertiary px-6 py-4">
            <AskAnythingComposer
              value={input}
              onChange={setInput}
              onSubmit={send}
              onCancel={() => abortControllerRef.current?.abort()}
              placeholder="Ask about this project…"
              ariaLabel="Ask about this project"
              busy={busy}
              projectId={projectId}
              className="mx-auto max-w-3xl"
            />
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={confirmDeleteId != null}
        title="Delete conversation?"
        message="This permanently deletes the conversation and all its messages."
        confirmLabel="Delete"
        onConfirm={() => {
          if (confirmDeleteId != null) deleteMutation.mutate(confirmDeleteId);
          setConfirmDeleteId(null);
        }}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </ProjectShell>
  );
}
