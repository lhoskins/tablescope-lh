"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  IconArrowUp,
  IconSparkles,
  IconPlus,
  IconTrash,
  IconMessageCircle,
  IconGitBranch,
  IconRefresh,
  IconDots,
  IconPencil,
} from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { cn } from "@/lib/cn";
import { getUserMeta } from "@/lib/auth";
import {
  useCurrentUser,
  useProjectSummaries,
  useConversations,
  useConversation,
  createConversation,
  sendConversationMessage,
  renameConversation,
  deleteConversation,
  branchConversation,
  type AiChatMessage,
  type AiChatMessageData,
  type AiConversation,
} from "@/lib/ui/use-shell-data";
import { ResultChart, ResultTable } from "@/components/ai/ai-result-view";
import { projectInsightApi } from "@/lib/api/project-insight";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";

const FALLBACK_USER: CurrentUser = {
  name: "",
  email: "",
  role: "",
  tenantName: "",
  initials: "··",
};
const FALLBACK_TENANT: TenantSummary = {
  name: "Tablescope",
  slug: "",
  initials: "TS",
};

export default function AiAssistantPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: identity } = useCurrentUser();
  const { data: projects } = useProjectSummaries();
  const { data: conversations } = useConversations();

  const [activeId, setActiveId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [projectId, setProjectId] = useState<number | null>(null);
  const [needsProject, setNeedsProject] = useState(false);
  const { data: active } = useConversation(activeId);
  const messages = active?.messages ?? [];
  const scrollRef = useRef<HTMLDivElement>(null);

  // Reflect the active conversation's project (if any) in the picker so a
  // returning thread stays scoped to the source it was answered against.
  useEffect(() => {
    setProjectId(active?.projectId ?? null);
    setNeedsProject(false);
  }, [active?.id, active?.projectId]);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const invalidateConvos = () =>
    queryClient.invalidateQueries({ queryKey: ["ai", "conversations"] });

  const sendMutation = useMutation({
    mutationFn: async ({
      question,
      pid,
      source,
    }: {
      question: string;
      pid: number | null;
      source?: string | null;
    }) => {
      let id = activeId;
      if (id == null) {
        const convo = await createConversation({ project_id: pid });
        id = convo.id;
        setActiveId(id);
      }
      return sendConversationMessage(id, question, pid, source ?? null);
    },
    onSuccess: (convo) => {
      queryClient.setQueryData(["ai", "conversation", convo.id], convo);
      invalidateConvos();
    },
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      renameConversation(id, title),
    onSuccess: (convo) => {
      queryClient.setQueryData(["ai", "conversation", convo.id], convo);
      invalidateConvos();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteConversation(id),
    onSuccess: (_data, id) => {
      if (activeId === id) setActiveId(null);
      invalidateConvos();
    },
  });

  const branchMutation = useMutation({
    mutationFn: ({ id, messageId }: { id: number; messageId?: number }) =>
      branchConversation(id, messageId),
    onSuccess: (convo) => {
      queryClient.setQueryData(["ai", "conversation", convo.id], convo);
      setActiveId(convo.id);
      invalidateConvos();
    },
  });

  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const busy = sendMutation.isPending;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, busy]);

  const send = (raw: string) => {
    const question = raw.trim();
    if (!question || busy) return;
    const pid = projectId ?? active?.projectId ?? null;
    if (pid == null) {
      // Prompt for the project instead of silently guessing one.
      setNeedsProject(true);
      return;
    }
    setNeedsProject(false);
    setInput("");
    sendMutation.mutate({ question, pid });
  };

  const retryLast = () => {
    if (busy || !sendMutation.variables) return;
    sendMutation.mutate(sendMutation.variables);
  };

  // Re-run a clarification question with the source the user picked, so the
  // resolver locks onto it instead of guessing again.
  const askWithSource = (question: string, source: string) => {
    if (busy) return;
    const pid = projectId ?? active?.projectId ?? null;
    if (pid == null) {
      setNeedsProject(true);
      return;
    }
    sendMutation.mutate({ question, pid, source });
  };

  // Suggested questions mirror the Project Insight page's "Questions to Ask";
  // fetched lazily (behind the button) and sharing that page's React Query
  // cache so build_project_insight is not recomputed.
  const [showSuggestions, setShowSuggestions] = useState(false);
  const suggestPid = projectId ?? active?.projectId ?? null;
  const insightQuery = useQuery({
    queryKey: ["project", String(suggestPid), "insight"],
    queryFn: () => projectInsightApi.get(String(suggestPid)),
    enabled: showSuggestions && suggestPid != null,
    staleTime: 5 * 60 * 1000,
  });
  const suggestedQuestions = (insightQuery.data?.questionsToAsk ?? [])
    .map((q) => q.question?.trim())
    .filter((q): q is string => !!q)
    .slice(0, 6);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  const pendingQuestion =
    busy && sendMutation.variables ? sendMutation.variables.question : null;

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
        <aside className="flex w-60 shrink-0 flex-col border-r border-line-tertiary bg-bg-secondary">
          <div className="border-b border-line-tertiary p-2.5">
            <Button
              variant="secondary"
              className="w-full justify-start gap-2"
              onClick={() => {
                setActiveId(null);
                setInput("");
              }}
            >
              <IconPlus size={14} />
              New chat
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {(conversations ?? []).length === 0 && (
              <p className="px-2 py-4 text-small text-ink-tertiary">
                No conversations yet.
              </p>
            )}
            {(conversations ?? []).map((c) => (
              <ConversationRow
                key={c.id}
                conversation={c}
                active={activeId === c.id}
                onSelect={() => setActiveId(c.id)}
                onRename={(title) =>
                  renameMutation.mutate({ id: c.id, title })
                }
                onBranch={() => branchMutation.mutate({ id: c.id })}
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
            {messages.length === 0 && !pendingQuestion ? (
              <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center text-center">
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-500">
                  <IconSparkles size={24} />
                </div>
                <h2 className="text-h2 text-ink-primary">
                  How can I help you?
                </h2>
                <p className="mt-1.5 text-small text-ink-tertiary">
                  Ask questions about your data, documents, or dashboards.
                  Conversations are saved automatically and used to improve
                  future answers.
                </p>
              </div>
            ) : (
              <div className="mx-auto max-w-3xl space-y-5">
                {messages.map((m) => (
                  <ChatBubble
                    key={m.id}
                    message={m}
                    onPickSource={askWithSource}
                    onBranch={
                      activeId != null && m.id > 0
                        ? () =>
                            branchMutation.mutate({
                              id: activeId,
                              messageId: m.id,
                            })
                        : undefined
                    }
                    branching={branchMutation.isPending}
                  />
                ))}
                {pendingQuestion && (
                  <ChatBubble
                    message={{
                      id: -1,
                      role: "user",
                      content: pendingQuestion,
                      createdAt: null,
                    }}
                  />
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
            <div className="mx-auto mb-2 flex max-w-3xl items-center gap-2">
              <label className="text-[12px] text-ink-tertiary">Project</label>
              <select
                value={projectId ?? ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setProjectId(v === "" ? null : Number(v));
                  if (v !== "") setNeedsProject(false);
                }}
                className={cn(
                  "min-w-0 flex-1 rounded-md border bg-bg-primary px-2 py-1.5 text-[12px] text-ink-primary focus:outline-none",
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
            <div className="mx-auto mb-2 flex max-w-3xl flex-col gap-2">
              <button
                type="button"
                onClick={() => setShowSuggestions((v) => !v)}
                disabled={suggestPid == null}
                className="self-start text-[12px] text-brand-500 hover:text-brand-700 disabled:opacity-40"
              >
                {showSuggestions ? "Hide suggestions" : "Suggest questions"}
              </button>
              {showSuggestions && insightQuery.isLoading && (
                <span className="text-[12px] text-ink-tertiary">
                  Loading suggestions…
                </span>
              )}
              {showSuggestions &&
                !insightQuery.isLoading &&
                suggestedQuestions.length === 0 && (
                  <span className="text-[12px] text-ink-tertiary">
                    No suggested questions for this project yet.
                  </span>
                )}
              {showSuggestions && suggestedQuestions.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {suggestedQuestions.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => send(q)}
                      disabled={busy}
                      className="rounded-full border border-line-secondary bg-bg-secondary px-3 py-1 text-[12px] text-ink-secondary hover:border-brand-500 hover:text-ink-primary disabled:opacity-40"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-line-secondary bg-bg-primary px-4 py-3 shadow-sm">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(input);
                  }
                }}
                rows={1}
                placeholder="Message Tablescope AI…"
                className="max-h-32 min-h-[24px] flex-1 resize-none bg-transparent text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none"
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

function ConversationRow({
  conversation,
  active,
  onSelect,
  onRename,
  onBranch,
  onDelete,
}: {
  conversation: AiConversation;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onBranch: () => void;
  onDelete: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conversation.title);

  const startRename = () => {
    setDraft(conversation.title);
    setEditing(true);
    setMenuOpen(false);
  };

  const commitRename = () => {
    const next = draft.trim();
    if (next && next !== conversation.title) onRename(next);
    setEditing(false);
  };

  return (
    <div
      className={cn(
        "group relative flex items-center gap-2 rounded-md px-2 py-2 text-[13px]",
        active
          ? "bg-brand-50 text-brand-700"
          : "text-ink-secondary hover:bg-bg-primary",
      )}
      onContextMenu={(e) => {
        e.preventDefault();
        setMenuOpen(true);
      }}
    >
      {conversation.parentConversationId ? (
        <IconGitBranch size={14} className="shrink-0" />
      ) : (
        <IconMessageCircle size={14} className="shrink-0" />
      )}
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") setEditing(false);
          }}
          className="min-w-0 flex-1 rounded border border-line-secondary bg-bg-primary px-1.5 py-0.5 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
        />
      ) : (
        <button
          type="button"
          onClick={onSelect}
          className="min-w-0 flex-1 truncate text-left"
          title={conversation.title}
        >
          {conversation.title}
        </button>
      )}
      {!editing && (
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="Conversation actions"
          className={cn(
            "shrink-0 rounded text-ink-tertiary hover:text-ink-secondary",
            menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100",
          )}
        >
          <IconDots size={15} />
        </button>
      )}
      {menuOpen && (
        <>
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setMenuOpen(false)}
          />
          <div className="absolute right-1 top-8 z-50 w-36 overflow-hidden rounded-md border border-line-tertiary bg-bg-primary py-1 shadow-lg">
            <MenuItem
              icon={<IconPencil size={14} />}
              label="Rename"
              onClick={startRename}
            />
            <MenuItem
              icon={<IconGitBranch size={14} />}
              label="Branch"
              onClick={() => {
                onBranch();
                setMenuOpen(false);
              }}
            />
            <MenuItem
              icon={<IconTrash size={14} />}
              label="Delete"
              danger
              onClick={() => {
                onDelete();
                setMenuOpen(false);
              }}
            />
          </div>
        </>
      )}
    </div>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-bg-secondary",
        danger ? "text-danger" : "text-ink-secondary",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function BranchButton({
  onBranch,
  branching,
}: {
  onBranch?: () => void;
  branching?: boolean;
}) {
  if (!onBranch) return null;
  return (
    <button
      type="button"
      onClick={onBranch}
      disabled={branching}
      title="Branch a new conversation from here"
      className="mt-1 inline-flex items-center gap-1 self-start rounded-md px-1.5 py-0.5 text-[11px] text-ink-tertiary opacity-0 transition-opacity hover:bg-bg-secondary hover:text-ink-secondary group-hover:opacity-100 disabled:opacity-50"
    >
      <IconGitBranch size={12} />
      Branch
    </button>
  );
}

function ChatBubble({
  message,
  onBranch,
  branching,
  onPickSource,
}: {
  message: AiChatMessage;
  onBranch?: () => void;
  branching?: boolean;
  onPickSource?: (question: string, source: string) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="group flex flex-col items-end gap-0">
        <div className="max-w-[75%] rounded-xl bg-brand px-4 py-3 text-[13px] leading-relaxed text-brand-fg">
          <span className="whitespace-pre-wrap">{message.content}</span>
        </div>
        <BranchButton onBranch={onBranch} branching={branching} />
      </div>
    );
  }
  const data = message.data;
  const hasData = !!data && ((data.rows?.length ?? 0) > 0 || !!data.sql);
  const clarify =
    !!data?.needsClarification &&
    (data.suggestedSources?.length ?? 0) > 0 &&
    !!data.question;
  const wide = hasData || clarify;
  return (
    <div className="group flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
        <IconSparkles size={16} />
      </div>
      <div className={cn("flex flex-col", wide ? "w-full" : "max-w-[75%]")}>
        <div className="rounded-xl bg-bg-secondary px-4 py-3 text-[13px] leading-relaxed text-ink-primary">
          <span className="whitespace-pre-wrap">{message.content}</span>
        </div>
        {hasData && data && <ChatResult data={data} />}
        {clarify && data && (
          <div className="mt-2 flex flex-wrap gap-2">
            {(data.suggestedSources ?? []).map((src) => (
              <button
                key={src}
                type="button"
                onClick={() => onPickSource?.(data.question ?? "", src)}
                disabled={!onPickSource}
                className="rounded-full border border-line-secondary bg-bg-primary px-3 py-1 text-[12px] text-ink-secondary hover:border-brand-500 hover:text-ink-primary disabled:opacity-40"
              >
                {src}
              </button>
            ))}
          </div>
        )}
        <BranchButton onBranch={onBranch} branching={branching} />
      </div>
    </div>
  );
}

function ChatResult({ data }: { data: AiChatMessageData }) {
  const [showSql, setShowSql] = useState(false);
  return (
    <div className="mt-2 rounded-xl border border-line-tertiary bg-bg-primary p-3">
      <ResultChart
        columns={data.columns}
        rows={data.rows}
        viz={data.suggestedVisualization}
      />
      <ResultTable columns={data.columns} rows={data.rows} />
      {data.sql && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setShowSql((v) => !v)}
            className="text-[11px] text-ink-tertiary hover:text-ink-secondary"
          >
            {showSql ? "Hide SQL" : "Show SQL"}
          </button>
          {showSql && (
            <pre className="mt-1 overflow-auto rounded-md bg-bg-secondary p-2 text-[11px] text-ink-secondary">
              {data.sql}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
