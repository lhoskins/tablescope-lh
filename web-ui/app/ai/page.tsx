"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconArrowUp,
  IconSparkles,
  IconPlus,
  IconTrash,
  IconMessageCircle,
  IconGitBranch,
  IconRefresh,
} from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { getUserMeta } from "@/lib/auth";
import {
  useCurrentUser,
  useProjectSummaries,
  useConversations,
  useConversation,
  createConversation,
  sendConversationMessage,
  deleteConversation,
  branchConversation,
  type AiChatMessage,
} from "@/lib/ui/use-shell-data";
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
  const { data: active } = useConversation(activeId);
  const messages = active?.messages ?? [];
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const invalidateConvos = () =>
    queryClient.invalidateQueries({ queryKey: ["ai", "conversations"] });

  const sendMutation = useMutation({
    mutationFn: async (question: string) => {
      let id = activeId;
      if (id == null) {
        const convo = await createConversation();
        id = convo.id;
        setActiveId(id);
      }
      return sendConversationMessage(id, question);
    },
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
    mutationFn: ({ id, messageId }: { id: number; messageId: number }) =>
      branchConversation(id, messageId),
    onSuccess: (convo) => {
      queryClient.setQueryData(["ai", "conversation", convo.id], convo);
      setActiveId(convo.id);
      invalidateConvos();
    },
  });

  const busy = sendMutation.isPending;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, busy]);

  const send = (raw: string) => {
    const question = raw.trim();
    if (!question || busy) return;
    setInput("");
    sendMutation.mutate(question);
  };

  const retryLast = () => {
    if (busy || !sendMutation.variables) return;
    sendMutation.mutate(String(sendMutation.variables));
  };

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  const pendingQuestion =
    busy && sendMutation.variables ? String(sendMutation.variables) : null;

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
              <div
                key={c.id}
                className={cn(
                  "group flex items-center gap-2 rounded-md px-2 py-2 text-[13px]",
                  activeId === c.id
                    ? "bg-brand-50 text-brand-700"
                    : "text-ink-secondary hover:bg-bg-primary",
                )}
              >
                {c.parentConversationId ? (
                  <IconGitBranch size={14} className="shrink-0" />
                ) : (
                  <IconMessageCircle size={14} className="shrink-0" />
                )}
                <button
                  type="button"
                  onClick={() => setActiveId(c.id)}
                  className="min-w-0 flex-1 truncate text-left"
                  title={c.title}
                >
                  {c.title}
                </button>
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate(c.id)}
                  aria-label="Delete conversation"
                  className="shrink-0 text-ink-tertiary opacity-0 hover:text-danger group-hover:opacity-100"
                >
                  <IconTrash size={13} />
                </button>
              </div>
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
    </AppShell>
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
}: {
  message: AiChatMessage;
  onBranch?: () => void;
  branching?: boolean;
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
  return (
    <div className="group flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
        <IconSparkles size={16} />
      </div>
      <div className="flex max-w-[75%] flex-col">
        <div className="rounded-xl bg-bg-secondary px-4 py-3 text-[13px] leading-relaxed text-ink-primary">
          <span className="whitespace-pre-wrap">{message.content}</span>
        </div>
        <BranchButton onBranch={onBranch} branching={branching} />
      </div>
    </div>
  );
}
