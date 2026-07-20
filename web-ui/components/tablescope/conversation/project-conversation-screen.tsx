"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  IconArrowUp,
  IconPlus,
  IconSparkles,
  IconTrash,
  IconMessage,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import { cn } from "@/lib/cn";
import { useProjectShell } from "@/lib/ui/use-project-data";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  submitTurn,
  type Conversation,
  type ConversationSummary,
} from "@/lib/api/conversational-analytics";

const QUICK_PROMPTS = [
  "Summarize this project's data",
  "Show me the top trends",
  "Which tables can be joined together?",
];

interface ProjectConversationScreenProps {
  projectId: string;
}

export function ProjectConversationScreen({ projectId }: ProjectConversationScreenProps) {
  const { project, tenant } = useProjectShell(projectId);
  const searchParams = useSearchParams();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSidebar, setShowSidebar] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const projectIdNum = Number(projectId);

  const loadConversations = useCallback(async () => {
    try {
      const data = await listConversations(projectIdNum);
      setConversations(data);
    } catch {
      // fail silently; conversation history is not critical to asking a question.
    }
  }, [projectIdNum]);

  useEffect(() => {
    const q = searchParams.get("q");
    if (q) setInput(q);
    loadConversations();
  }, [searchParams, loadConversations]);

  // Load a specific conversation when arriving from "Open in AI Assistant".
  const hasSelectedFromQuery = useRef(false);
  useEffect(() => {
    const idParam = searchParams.get("conversation");
    const id = idParam ? Number(idParam) : null;
    if (id && !hasSelectedFromQuery.current) {
      hasSelectedFromQuery.current = true;
      void selectConversation(id);
    }
  }, [searchParams]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [conversation?.turns, busy]);

  async function startNew() {
    setConversation(null);
    setInput("");
    setError(null);
    await loadConversations();
  }

  async function send(raw: string) {
    const message = raw.trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    setError(null);

    try {
      if (!conversation) {
        const created = await createConversation({
          project_id: projectIdNum,
          initial_message: message,
        });
        setConversation(created);
        await loadConversations();
      } else {
        const updated = await submitTurn(conversation.id, { message });
        setConversation((prev) => {
          if (!prev) return prev;
          const turns = [...prev.turns, updated.turn];
          return { ...prev, turns, updated_at: new Date().toISOString() };
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function selectConversation(id: number) {
    setBusy(true);
    setError(null);
    try {
      const data = await getConversation(id);
      setConversation(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load conversation.");
    } finally {
      setBusy(false);
    }
  }

  async function removeConversation(id: number, e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await deleteConversation(id);
      if (conversation?.id === id) {
        setConversation(null);
      }
      await loadConversations();
    } catch {
      // ignore
    }
  }

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-ask-tablescope"
      breadcrumbLabel="Ask TableScope"
      actions={
        <>
          <Button variant="secondary" onClick={() => setShowSidebar((v) => !v)}>
            <IconMessage size={14} />
            History
          </Button>
          <Button variant="primary" onClick={startNew}>
            <IconPlus size={14} />
            New chat
          </Button>
        </>
      }
      contextPanel={
        <AiContextRail projectId={projectId} conversation={conversation} />
      }
    >
      <div className="flex h-full gap-3 overflow-hidden">
        {showSidebar && (
          <aside className="flex w-56 shrink-0 flex-col rounded-lg border border-line-tertiary bg-bg-tertiary p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-h2 text-ink-primary">History</span>
              <button
                type="button"
                onClick={() => setShowSidebar(false)}
                className="text-ink-tertiary hover:text-ink-primary"
              >
                ×
              </button>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto">
              {conversations.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => selectConversation(c.id)}
                  className={cn(
                    "group flex w-full items-center justify-between rounded-md border px-2 py-1.5 text-left text-[12px]",
                    conversation?.id === c.id
                      ? "border-brand-500 bg-brand-50 text-ink-primary"
                      : "border-line-tertiary bg-bg-primary text-ink-secondary hover:border-brand-500"
                  )}
                >
                  <span className="truncate">{c.title}</span>
                  <IconTrash
                    size={12}
                    className="shrink-0 opacity-0 group-hover:opacity-50"
                    onClick={(e) => removeConversation(c.id, e)}
                  />
                </button>
              ))}
              {conversations.length === 0 && (
                <p className="text-[12px] text-ink-tertiary">No conversations yet.</p>
              )}
            </div>
          </aside>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-brand-100 bg-brand-50/50 px-3 py-2 text-[13px] text-ink-secondary">
            <IconSparkles size={15} className="text-brand-500" />
            <span>
              AI scoped to{" "}
              <span className="font-medium text-ink-primary">
                {project?.name ?? "this project"}
              </span>{" "}
              · Tenant: {tenant.name} · Cross-project disabled
            </span>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto pb-4">
            {!conversation || conversation.turns.length === 0 ? (
              <div className="mx-auto max-w-xl py-12 text-center">
                <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-500">
                  <IconSparkles size={22} />
                </div>
                <div className="text-h2 text-ink-primary">
                  Ask anything about {project?.name ?? "this project"}
                </div>
                <p className="mt-1 text-small text-ink-tertiary">
                  Get answers grounded in this project&apos;s data and documents. Follow up,
                  refine charts, and save results.
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
              conversation.turns.map((t) => (
                <TurnBubble
                  key={t.id}
                  turn={t}
                  onFollowUp={(text) => send(text)}
                  isLast={t.id === conversation.turns[conversation.turns.length - 1].id}
                />
              ))
            )}
            {busy && (
              <div className="flex gap-2.5">
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500">
                  <IconSparkles size={15} />
                </div>
                <div className="max-w-[80%] rounded-lg border border-line-tertiary bg-bg-primary px-3.5 py-2.5 text-[13px] leading-relaxed text-ink-primary">
                  <span className="text-ink-tertiary">Thinking…</span>
                </div>
              </div>
            )}
            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">
                {error}
              </div>
            )}
          </div>

          <div className="border-t border-line-tertiary pt-3">
            <div className="flex items-end gap-2 rounded-lg border border-line-secondary bg-bg-primary px-3 py-2">
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
                placeholder={`Ask about your data, documents, or dashboards in ${project?.name ?? "this project"}…`}
                aria-label="Ask about your project"
                className="flex-1 text-[13px] text-ink-primary placeholder:text-ink-tertiary"
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
              AI responses are scoped to this project and tenant only. All actions are audited.
            </p>
          </div>
        </div>
      </div>
    </ProjectShell>
  );
}

function AiContextRail({
  projectId,
  conversation,
}: {
  projectId: string;
  conversation: Conversation | null;
}) {
  const { project, tenant } = useProjectShell(projectId);
  return (
    <aside className="flex w-rail shrink-0 flex-col border-l border-line-tertiary bg-bg-tertiary">
      <div className="flex items-center justify-between px-4 py-3.5">
        <span className="text-h2 text-ink-primary">Conversation</span>
        <StatusDot tone="online" />
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto px-4 pb-4">
        <Section title="Active Context">
          <dl className="space-y-1 text-[13px]">
            <RailRow label="Tenant" value={tenant.name} />
            <RailRow label="Project" value={project?.name ?? "—"} />
            <RailRow label="Conversation" value={conversation?.title ?? "—"} />
            <RailRow label="Turns" value={String(conversation?.turns.length ?? 0)} />
            <RailRow label="Cross-project" value="off" />
          </dl>
        </Section>
        <Section title="Scope">
          <div className="flex flex-wrap gap-1.5">
            <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[11px] text-brand-700">
              Project data
            </span>
            <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-700">
              Documents
            </span>
          </div>
        </Section>
      </div>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line-tertiary bg-bg-primary p-3">
      <div className="mb-2 text-caption uppercase tracking-wide text-ink-tertiary">
        {title}
      </div>
      {children}
    </section>
  );
}

function RailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-ink-tertiary">{label}</dt>
      <dd className={cn("truncate text-ink-primary")}>{value}</dd>
    </div>
  );
}
