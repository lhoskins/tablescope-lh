"use client";


import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconSparkles,
  IconTrash,
  IconRefresh,
  IconDots,
  IconPencil,
  IconMenu2,
} from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { AskAnythingComposer } from "@/components/ai/ask-anything-composer";
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
import type { CurrentUser, ProjectSummary, TenantSummary } from "@/lib/ui/types";
import { AssistantHeader } from "./assistant-header";
import { FALLBACK_USER } from "./fallback-user";
import { FALLBACK_TENANT } from "./fallback-tenant";
import { CHART_FOLLOW_UPS } from "./chart-follow-ups";
import { ConversationListPanel } from "./conversation-list-panel";
import { MobileConversationDrawer } from "./mobile-conversation-drawer";
import { UserBubble } from "./user-bubble";
import { TurnBubbles } from "./turn-bubbles";
import { groupConversationSummaries } from "@/lib/conversations/group-canonical";



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
  // An explicit pick narrows which project a new conversation is scoped to.
  // It is never required — when unset, the backend resolves the most
  // relevant authorized project from the question itself.
  const [projectId, setProjectId] = useState<number | null>(null);
  const [paramsRead, setParamsRead] = useState(false);
  const [autoStarted, setAutoStarted] = useState(false);
  // Stores the question seeded from a deep-link (the ?q=... param). We keep it
  // separate from the live composer input so user typing does not accidentally
  // trigger the auto-start behaviour on the first keystroke.
  const [autoStartQuestion, setAutoStartQuestion] = useState<string | null>(null);
  // Set only from a deep link, so "View all project conversations" lands on a
  // list already narrowed to that project.
  const [projectFilter, setProjectFilter] = useState<number | null>(null);
  const [pendingTurnId, setPendingTurnId] = useState<number | null>(null);
  const [mobileConversationsOpen, setMobileConversationsOpen] = useState(false);
  const { data: active } = useQuery({
    queryKey: ["conversational-analytics", "conversation", activeId],
    queryFn: () => getConversation(activeId as number),
    enabled: activeId != null,
  });
  const turns = active?.turns ?? [];
  const assistantConversations = (conversations ?? []).filter(
    (c) => projectFilter == null || c.project_id === projectFilter,
  );

  // Group canonical Insight threads so the sidebar shows one durable Business
  // Insights row and one Project Insights row per project. Manual chats remain
  // individual rows.
  const groupedConversations = useMemo<ConversationSummary[]>(
    () => groupConversationSummaries(assistantConversations, projects ?? []),
    [assistantConversations, projects],
  );

  // Deterministic Project Overview back navigation based on the URL and the
  // authorized project list. Never derive it from browser history or referrer.
  const returnProject = useMemo<ProjectSummary | null>(() => {
    if (searchParams.get("from") !== "project-overview") return null;
    const rawProjectId = searchParams.get("projectId");
    if (!rawProjectId || !/^\d+$/.test(rawProjectId)) return null;
    const projectId = Number(rawProjectId);
    if (projectId <= 0) return null;
    return (
      projects?.find((p) => Number(p.id) === projectId) ?? null
    );
  }, [searchParams, projects]);
  const turnCount = turns.length;
  const scrollRef = useRef<HTMLDivElement>(null);
  // AbortController for the in-flight turn so the user can cancel a long-running
  // AI request from the composer.
  const abortControllerRef = useRef<AbortController | null>(null);

  // Read-only: which project the current conversation resolved to. This lets
  // users see (and debug) what the backend chose when a question wasn't
  // explicitly scoped, even while the optional picker is still visible.
  const resolvedProjectName = useMemo(() => {
    const pid = active?.project_id;
    if (pid == null) return null;
    return projects?.find((p) => Number(p.id) === pid)?.name ?? null;
  }, [active?.project_id, projects]);

  // A conversation is scoped to one project for grounded answers; reflect it
  // in the picker (and lock the picker) while that thread is open.
  useEffect(() => {
    if (active?.project_id != null) setProjectId(active.project_id);
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
    if (q) {
      setInput(q);
      setAutoStartQuestion(q);
    }
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
      // Omitted when the user hasn't narrowed to a project — the backend
      // (resolve_business_insight_project) picks the best authorized project
      // from the question itself, the same resolver Business Insights uses.
      pid: number | undefined;
    }): Promise<Conversation | { conversation_id: number }> => {
      const signal = abortControllerRef.current?.signal;
      if (activeId == null) {
        const convo = await createConversation(
          { project_id: pid, initial_message: question },
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
      setInput("");
      // A picked project narrows the request; otherwise leave it unset so
      // the backend resolves the project from the question.
      const pid = active?.project_id ?? projectId ?? undefined;
      abortControllerRef.current = new AbortController();
      sendMutation.mutate({ question, pid });
    },
    [active, projectId, busy, sendMutation],
  );

  // Auto-start a conversation seeded from the deep-link parameters once.
  // Only the ?q=... param should trigger an automatic send; user typing should
  // never be auto-submitted on the first keystroke.
  useEffect(() => {
    if (!paramsRead || autoStarted || !autoStartQuestion?.trim()) return;
    setAutoStarted(true);
    send(autoStartQuestion.trim());
  }, [paramsRead, autoStarted, autoStartQuestion, send]);

  const retryLast = () => {
    if (busy || !sendMutation.variables) return;
    abortControllerRef.current = new AbortController();
    sendMutation.mutate(sendMutation.variables);
  };

  const cancelLast = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    sendMutation.reset();
  }, [sendMutation]);

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
      topBarLeft={<AssistantHeader returnProject={returnProject} />}
      scrollable={false}
    >
      <div className="relative flex h-[calc(100dvh-6.5rem)] min-h-0 flex-col gap-0 overflow-hidden rounded-lg border border-line-tertiary lg:flex-row">
        {/* Left sidebar — conversations (desktop) */}
        <aside className="hidden w-[260px] shrink-0 flex-col border-r border-line-tertiary bg-bg-secondary lg:flex">
          <ConversationListPanel
            conversations={groupedConversations}
            activeId={activeId}
            onNew={() => {
              setActiveId(null);
              setInput("");
              setProjectId(null);
              setProjectFilter(null);
            }}
            onSelect={setActiveId}
            onRename={(id, title) => renameMutation.mutate({ id, title })}
            onDelete={(id) => setConfirmDeleteId(id)}
          />
        </aside>

        <MobileConversationDrawer
          open={mobileConversationsOpen}
          onClose={() => setMobileConversationsOpen(false)}
          conversations={groupedConversations}
          activeId={activeId}
          onNew={() => {
            setActiveId(null);
            setInput("");
            setProjectId(null);
            setProjectFilter(null);
            setMobileConversationsOpen(false);
          }}
          onSelect={(id) => {
            setActiveId(id);
            setMobileConversationsOpen(false);
          }}
          onRename={(id, title) => renameMutation.mutate({ id, title })}
          onDelete={(id) => setConfirmDeleteId(id)}
        />

        {/* Right — chat area */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-bg-primary">
          {/* Mobile conversation toggle */}
          <div className="flex items-center justify-end border-b border-line-tertiary px-4 py-2 lg:hidden">
            <button
              type="button"
              onClick={() => setMobileConversationsOpen(true)}
              aria-label="Open conversations"
              className="inline-flex h-9 items-center gap-2 rounded-md px-3 text-[12px] font-medium text-ink-secondary hover:bg-bg-secondary"
            >
              <IconMenu2 size={18} />
              Conversations
            </button>
          </div>
          {/* Messages */}
          <div
            ref={scrollRef}
            className="min-h-0 flex-1 overflow-y-auto px-6 py-5"
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
            {resolvedProjectName && (
              <p className="mx-auto mb-2 max-w-3xl text-[11px] text-ink-tertiary">
                Answered from{" "}
                <span className="font-medium text-ink-secondary">
                  {resolvedProjectName}
                </span>
              </p>
            )}
            <AskAnythingComposer
              value={input}
              onChange={setInput}
              onSubmit={send}
              onCancel={busy ? cancelLast : undefined}
              placeholder="Message Tablescope AI…"
              ariaLabel="Message Tablescope AI"
              busy={busy}
              projectId={projectId}
              className="mx-auto max-w-3xl"
            />
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
