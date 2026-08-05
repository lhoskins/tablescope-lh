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
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";import { FALLBACK_USER } from "./fallback-user";
import { FALLBACK_TENANT } from "./fallback-tenant";
import { CHART_FOLLOW_UPS } from "./chart-follow-ups";
import { ConversationRow } from "./conversation-row";
import { UserBubble } from "./user-bubble";
import { TurnBubbles } from "./turn-bubbles";



function AiAssistantPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { data: identity } = useCurrentUser();
  const { data: projects } = useProjectSummaries();
  const { data: conversations } = useQuery({
    queryKey: ["conversational-analytics", "conversations"],
    queryFn: () => listConversations(),
  });

  const [activeId, setActiveId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [projectId, setProjectId] = useState<number | null>(null);
  const [needsProject, setNeedsProject] = useState(false);
  const [paramsRead, setParamsRead] = useState(false);
  const [autoStarted, setAutoStarted] = useState(false);
  // Set only from a deep link, so "View all project conversations" lands on a
  // list already narrowed to that project.
  const [projectFilter, setProjectFilter] = useState<number | null>(null);
  const [pendingTurnId, setPendingTurnId] = useState<number | null>(null);
  const { data: active } = useQuery({
    queryKey: ["conversational-analytics", "conversation", activeId],
    queryFn: () => getConversation(activeId as number),
    enabled: activeId != null,
  });
  const turns = active?.turns ?? [];
  const assistantConversations = (conversations ?? []).filter(
    (c) => projectFilter == null || c.project_id === projectFilter,
  );
  const turnCount = turns.length;
  const scrollRef = useRef<HTMLDivElement>(null);

  // A conversation is scoped to one project for grounded answers; reflect it
  // in the picker (and lock the picker) while that thread is open.
  useEffect(() => {
    if (active?.project_id != null) setProjectId(active.project_id);
    setNeedsProject(false);
  }, [active?.id, active?.project_id]);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  // Hydrate project + prompt + existing conversation from a deep link.
  useEffect(() => {
    if (paramsRead) return;
    const q = searchParams.get("q");
    const pid = searchParams.get("projectId");
    const cid = searchParams.get("conversation");
    if (q) setInput(q);
    if (pid) {
      const n = Number(pid);
      if (!Number.isNaN(n)) {
        setProjectId(n);
        setProjectFilter(n);
      }
    }
    if (cid) {
      const n = Number(cid);
      if (!Number.isNaN(n)) setActiveId(n);
    }
    const tid = searchParams.get("turn");
    if (tid) {
      const n = Number(tid);
      if (!Number.isNaN(n)) setPendingTurnId(n);
    }
    setParamsRead(true);
  }, [searchParams, paramsRead]);

  const invalidateConvos = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: ["conversational-analytics", "conversations"],
      }),
    [queryClient],
  );

  const invalidateActive = (id: number) =>
    queryClient.invalidateQueries({
      queryKey: ["conversational-analytics", "conversation", id],
    });

  const sendMutation = useMutation({
    mutationFn: async ({
      question,
      pid,
    }: {
      question: string;
      pid: number;
    }): Promise<Conversation | { conversation_id: number }> => {
      if (activeId == null) {
        const convo = await createConversation({
          project_id: pid,
          initial_message: question,
        });
        setActiveId(convo.id);
        return convo;
      }
      return submitTurn(activeId, { message: question });
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

  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const busy = sendMutation.isPending;

  useEffect(() => {
    if (pendingTurnId != null) return;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turnCount, busy, pendingTurnId]);

  // Deep links may target one turn inside a long conversation.
  useEffect(() => {
    if (pendingTurnId == null || turnCount === 0) return;
    const target = document.getElementById(`turn-${pendingTurnId}`);
    if (!target) return;
    target.scrollIntoView({ block: "start" });
    setPendingTurnId(null);
  }, [pendingTurnId, turnCount]);

  const send = useCallback(
    (raw: string) => {
      const question = raw.trim();
      if (!question || busy) return;
      if (activeId == null && projectId == null) {
        // Prompt for the project only when creating a brand-new conversation.
        setNeedsProject(true);
        return;
      }
      setNeedsProject(false);
      setInput("");
      const pid = active?.project_id ?? projectId ?? 0;
      sendMutation.mutate({ question, pid });
    },
    [active, activeId, projectId, busy, sendMutation],
  );

  // Auto-start a conversation seeded from the deep-link parameters once.
  useEffect(() => {
    if (!paramsRead || autoStarted || !input.trim()) return;
    // Need either an existing conversation (submit) or a project to create one.
    if (activeId == null && projectId == null) return;
    setAutoStarted(true);
    const question = input.trim();
    send(question);
  }, [paramsRead, autoStarted, input, projectId, activeId, send]);

  const retryLast = () => {
    if (busy || !sendMutation.variables) return;
    sendMutation.mutate(sendMutation.variables);
  };

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  const pendingQuestion =
    busy && sendMutation.variables ? sendMutation.variables.question : null;

  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const showFollowUps =
    !busy && lastTurn?.status === "success" && !!lastTurn?.chart_config;

  return (
    <AppShell
      mode="home"
      activeNav="ai-assistant"
      tenant={tenant}
      user={user}
      counts={{ projects: projects?.length }}
      topBarLeft={
        <span className="text-h2 text-ink-primary">AI Assistant</span>
      }
    >
      <div className="flex h-[calc(100vh-9rem)] gap-0 overflow-hidden rounded-lg border border-line-tertiary">
        {/* Left sidebar — conversations */}
        <aside className="flex w-[260px] shrink-0 flex-col border-r border-line-tertiary bg-bg-secondary">
          <div className="border-b border-line-tertiary p-2.5">
            <Button
              variant="secondary"
              className="w-full justify-start gap-2"
              onClick={() => {
                setActiveId(null);
                setInput("");
                setProjectId(null);
                setProjectFilter(null);
              }}
            >
              <IconPlus size={14} />
              New chat
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {assistantConversations.length === 0 && (
              <p className="px-2 py-4 text-small text-ink-tertiary">
                No conversations yet.
              </p>
            )}
            {assistantConversations.map((c) => (
              <ConversationRow
                key={c.id}
                conversation={c}
                active={activeId === c.id}
                onSelect={() => setActiveId(c.id)}
                onRename={(title) =>
                  renameMutation.mutate({ id: c.id, title })
                }
                onDelete={() => setConfirmDeleteId(c.id)}
              />
            ))}
          </div>
        </aside>

        {/* Right — chat area */}
        <div className="flex min-w-0 flex-1 flex-col bg-bg-primary">
          {/* Messages */}
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto px-6 py-5"
          >
            {turns.length === 0 && !pendingQuestion ? (
              <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center text-center">
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-500">
                  <IconSparkles size={24} />
                </div>
                <h2 className="text-h2 text-ink-primary">
                  How can I help you?
                </h2>
                <p className="mt-1.5 text-small text-ink-tertiary">
                  Ask a data question and I&apos;ll answer with a real query,
                  chart, and table. Follow up in plain language to refine the
                  data or change the chart format.
                </p>
              </div>
            ) : (
              <div className="mx-auto max-w-3xl space-y-5">
                {turns.map((t) => (
                  <div key={t.id} id={`turn-${t.id}`}>
                    <TurnBubbles turn={t} />
                  </div>
                ))}
                {pendingQuestion && (
                  <UserBubble content={pendingQuestion} />
                )}
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
                      {(sendMutation.error as Error)?.message ??
                        "Something went wrong."}
                    </span>
                    <button
                      type="button"
                      onClick={retryLast}
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

          {/* Input area — bottom */}
          <div className="border-t border-line-tertiary px-6 py-4">
            {showFollowUps && (
              <div className="mx-auto mb-2 flex max-w-3xl flex-wrap gap-1.5">
                {CHART_FOLLOW_UPS.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => send(chip)}
                    className="rounded-full border border-line-secondary bg-bg-primary px-2.5 py-1 text-[12px] text-ink-secondary hover:border-brand-500 hover:text-brand-700"
                  >
                    {chip}
                  </button>
                ))}
              </div>
            )}
            <div className="mx-auto mb-2 flex max-w-3xl items-center gap-2">
              <label className="text-[12px] text-ink-tertiary">Project</label>
              <select
                value={active?.project_id ?? projectId ?? ""}
                disabled={active != null}
                onChange={(e) => {
                  const v = e.target.value;
                  setProjectId(v === "" ? null : Number(v));
                  if (v !== "") setNeedsProject(false);
                }}
                className={cn(
                  "min-w-0 flex-1 rounded-md border bg-bg-primary px-2 py-1.5 text-[12px] text-ink-primary focus:outline-none disabled:opacity-60",
                  needsProject
                    ? "border-danger focus:border-danger"
                    : "border-line-secondary focus:border-brand-500",
                )}
              >
                <option value="">Select a project…</option>
                {(projects ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            {needsProject && (
              <p className="mx-auto mb-2 max-w-3xl text-[12px] text-danger">
                Please choose a project so I know which data to use.
              </p>
            )}
            <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-line-secondary bg-bg-primary px-4 py-3 shadow-sm">
              <AutosizeTextarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(input);
                  }
                }}
                minRows={2}
                maxRows={8}
                placeholder="Message Tablescope AI…"
                aria-label="Message Tablescope AI"
                className="flex-1 text-[13px] text-ink-primary placeholder:text-ink-tertiary"
              />
              <button
                type="button"
                onClick={() => send(input)}
                disabled={busy || !input.trim()}
                aria-label="Send"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand text-brand-fg hover:bg-brand-700 disabled:opacity-40"
              >
                <IconArrowUp size={16} />
              </button>
            </div>
            <p className="mt-2 text-center text-[11px] text-ink-tertiary">
              Tablescope AI may produce inaccurate information. All responses
              are scoped to your tenant.
            </p>
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
    </AppShell>
  );
}

export default function AiAssistantPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center text-ink-secondary">
          Loading AI Assistant…
        </div>
      }
    >
      <AiAssistantPageInner />
    </Suspense>
  );
}
