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

const QUICK_PROMPTS = [
  "Summarize what my data contains",
  "Which tables can be joined together?",
  "What are the key insights from my documents?",
];

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

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length]);

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

  const busy = sendMutation.isPending;

  const send = (raw: string) => {
    const question = raw.trim();
    if (!question || busy) return;
    setInput("");
    sendMutation.mutate(question);
  };

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  // Optimistic view: when sending the first message, show it immediately.
  const pendingQuestion =
    busy && sendMutation.variables ? String(sendMutation.variables) : null;

  return (
    <AppShell
      mode="home"
      activeNav="ai-assistant"
      tenant={tenant}
      user={user}
      counts={{ projects: projects?.length }}
      topBarLeft={<span className="text-h2 text-ink-primary">AI Assistant</span>}
      topBarRight={
        <Button
          variant="primary"
          size="md"
          onClick={() => {
            setActiveId(null);
            setInput("");
          }}
        >
          <IconPlus size={15} />
          New chat
        </Button>
      }
    >
      <div className="flex h-[calc(100vh-9rem)] gap-4">
        {/* Saved conversations */}
        <aside className="flex w-64 shrink-0 flex-col overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
          <div className="border-b border-line-tertiary px-3 py-2.5 text-caption uppercase tracking-wide text-ink-tertiary">
            Saved conversations
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {(conversations ?? []).length === 0 && (
              <p className="px-2 py-4 text-small text-ink-tertiary">
                No saved conversations yet.
              </p>
            )}
            {(conversations ?? []).map((c) => (
              <div
                key={c.id}
                className={cn(
                  "group flex items-center gap-2 rounded-md px-2 py-2 text-[13px]",
                  activeId === c.id
                    ? "bg-brand-50 text-brand-700"
                    : "text-ink-secondary hover:bg-bg-secondary",
                )}
              >
                <IconMessageCircle size={15} className="shrink-0" />
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
                  <IconTrash size={14} />
                </button>
              </div>
            ))}
          </div>
        </aside>

        {/* Chat */}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-5">
            {messages.length === 0 && !pendingQuestion ? (
              <div className="mx-auto max-w-xl py-12 text-center">
                <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-500">
                  <IconSparkles size={22} />
                </div>
                <div className="text-h2 text-ink-primary">
                  Ask anything about your data
                </div>
                <p className="mt-1 text-small text-ink-tertiary">
                  Answers are grounded in your tenant&apos;s projects and
                  documents. Conversations are saved automatically.
                </p>
                <div className="mt-5 flex flex-col gap-2">
                  {QUICK_PROMPTS.map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => send(p)}
                      className="rounded-lg border border-line-secondary bg-bg-primary px-3 py-2 text-left text-[13px] text-ink-secondary hover:border-brand-500 hover:bg-brand-50/40"
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {messages.map((m) => (
                  <ChatBubble key={m.id} message={m} />
                ))}
                {pendingQuestion && messages.length === 0 && (
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
                  <div className="flex gap-2.5">
                    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
                      <IconSparkles size={15} />
                    </div>
                    <div className="rounded-lg border border-line-tertiary bg-bg-primary px-3.5 py-2.5 text-[13px] text-ink-tertiary">
                      Thinking…
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="border-t border-line-tertiary p-3">
            <div className="flex items-end gap-2 rounded-lg border border-line-secondary bg-bg-primary px-3 py-2">
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
                placeholder="Ask about your data, documents, or dashboards…"
                className="max-h-32 min-h-[24px] flex-1 resize-none bg-transparent text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none"
              />
              <button
                type="button"
                onClick={() => send(input)}
                disabled={busy || !input.trim()}
                aria-label="Send"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-brand text-brand-fg hover:bg-brand-700 disabled:opacity-40"
              >
                <IconArrowUp size={15} />
              </button>
            </div>
            <p className="mt-1.5 text-center text-small text-ink-tertiary">
              AI responses are scoped to your tenant only. All actions are
              audited.
            </p>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function ChatBubble({ message }: { message: AiChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg bg-brand px-3.5 py-2.5 text-[13px] leading-relaxed text-brand-fg">
          {message.content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex gap-2.5">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
        <IconSparkles size={15} />
      </div>
      <div className="max-w-[80%] rounded-lg border border-line-tertiary bg-bg-primary px-3.5 py-2.5 text-[13px] leading-relaxed text-ink-primary">
        <span className="whitespace-pre-wrap">{message.content}</span>
      </div>
    </div>
  );
}
