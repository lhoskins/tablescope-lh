"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconArrowUp,
  IconSparkles,
  IconPlus,
  IconTrash,
  IconMessageCircle,
  IconRefresh,
  IconDots,
  IconPencil,
} from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
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

const CHART_FOLLOW_UPS = [
  "change it to a line chart",
  "change it to a horizontal bar chart",
  "change it to a donut chart",
  "sort by value descending",
  "show as a table",
];

export default function AiAssistantPage() {
  const router = useRouter();
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
  const { data: active } = useQuery({
    queryKey: ["conversational-analytics", "conversation", activeId],
    queryFn: () => getConversation(activeId as number),
    enabled: activeId != null,
  });
  const turns = active?.turns ?? [];
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

  const invalidateConvos = () =>
    queryClient.invalidateQueries({
      queryKey: ["conversational-analytics", "conversations"],
    });
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
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns.length, busy]);

  const send = (raw: string) => {
    const question = raw.trim();
    if (!question || busy) return;
    const pid = active?.project_id ?? projectId;
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
        <aside className="flex w-60 shrink-0 flex-col border-r border-line-tertiary bg-bg-secondary">
          <div className="border-b border-line-tertiary p-2.5">
            <Button
              variant="secondary"
              className="w-full justify-start gap-2"
              onClick={() => {
                setActiveId(null);
                setInput("");
                setProjectId(null);
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
                  <TurnBubbles key={t.id} turn={t} />
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
  onDelete,
}: {
  conversation: ConversationSummary;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
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
      <IconMessageCircle size={14} className="shrink-0" />
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

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex flex-col items-end">
      <div className="max-w-[75%] rounded-xl bg-brand px-4 py-3 text-[13px] leading-relaxed text-brand-fg">
        <span className="whitespace-pre-wrap">{content}</span>
      </div>
    </div>
  );
}

/** One conversational-analytics turn: the user's message + the AI answer. */
function TurnBubbles({ turn }: { turn: ConversationTurn }) {
  const result = turn.result;
  const hasData = (result?.rows?.length ?? 0) > 0;
  return (
    <>
      <UserBubble content={turn.user_message} />
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
          <IconSparkles size={16} />
        </div>
        <div className={cn("flex flex-col", hasData ? "w-full" : "max-w-[75%]")}>
          <div
            className={cn(
              "rounded-xl bg-bg-secondary px-4 py-3 text-[13px] leading-relaxed",
              turn.status === "error" ? "text-danger" : "text-ink-primary",
            )}
          >
            <span className="whitespace-pre-wrap">
              {turn.assistant_message ??
                (turn.status === "pending" ? "Working on it…" : "")}
            </span>
          </div>
          {hasData && result && <TurnResult turn={turn} />}
        </div>
      </div>
    </>
  );
}

function TurnResult({ turn }: { turn: ConversationTurn }) {
  const [showSql, setShowSql] = useState(false);
  const result = turn.result;
  if (!result) return null;
  const chart = turn.chart_config;
  // Map the persisted chart config onto the shared renderer contract; the
  // subtype (horizontal_bar, donut, …) rides through as chartStyle.
  const viz: SuggestedVisualization = chart
    ? {
        type: chart.type as SuggestedVisualization["type"],
        xField: chart.labelColumn,
        yField: chart.valueColumns?.[0],
        chartStyle: chart.subtype,
      }
    : { type: "table" };
  return (
    <div className="mt-2 rounded-xl border border-line-tertiary bg-bg-primary p-3">
      {chart && chart.type !== "table" && (
        <ResultChart columns={result.columns} rows={result.rows} viz={viz} />
      )}
      <ResultTable columns={result.columns} rows={result.rows} />
      {turn.sql && (
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
              {turn.sql}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
