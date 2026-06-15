"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  IconArrowUp,
  IconSparkles,
  IconPlus,
  IconHistory,
} from "@tabler/icons-react";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { StatusDot } from "@/components/tablescope/status-dot";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { useProjectShell, askProjectAi } from "@/lib/ui/use-project-data";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
}

const QUICK_PROMPTS = [
  "Summarize what this project contains",
  "Which tables can be joined together?",
  "What are the key insights from my documents?",
];

export function AiAssistantScreen({ projectId }: { projectId: string }) {
  const { project, tenant } = useProjectShell(projectId);
  const searchParams = useSearchParams();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  // Prefill the composer when arriving from the Overview hero / quick prompts.
  useEffect(() => {
    const q = searchParams.get("q");
    if (q) setInput(q);
  }, [searchParams]);

  const send = async (raw: string) => {
    const question = raw.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [
      ...m,
      { role: "user", content: question },
      { role: "assistant", content: "", pending: true },
    ]);
    try {
      const res = await askProjectAi(projectId, question);
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = { role: "assistant", content: res.answer };
        return next;
      });
    } catch (err) {
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = {
          role: "assistant",
          content:
            err instanceof Error
              ? `Sorry — I couldn't answer that. ${err.message}`
              : "Sorry — something went wrong.",
        };
        return next;
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ProjectShell
      projectId={projectId}
      activeNav="project-ai-assistant"
      breadcrumbLabel="AI Assistant"
      actions={
        <>
          <Button variant="secondary">
            <IconHistory size={14} />
            History
          </Button>
          <Button variant="primary" onClick={() => setMessages([])}>
            <IconPlus size={14} />
            New chat
          </Button>
        </>
      }
      contextPanel={<AiContextRail projectId={projectId} />}
    >
      <div className="flex h-full flex-col">
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

        <div className="flex-1 space-y-4 overflow-y-auto pb-4">
          {messages.length === 0 ? (
            <div className="mx-auto max-w-xl py-12 text-center">
              <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-500">
                <IconSparkles size={22} />
              </div>
              <div className="text-h2 text-ink-primary">
                Ask anything about {project?.name ?? "this project"}
              </div>
              <p className="mt-1 text-small text-ink-tertiary">
                Answers are grounded in this project&apos;s data, documents and
                dashboards — and every action is audited.
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
            messages.map((m, i) => <ChatBubble key={i} message={m} />)
          )}
        </div>

        <div className="border-t border-line-tertiary pt-3">
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
              placeholder={`Ask about your data, documents, or dashboards in ${project?.name ?? "this project"}…`}
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
            AI responses are scoped to this project and tenant only. All actions
            are audited.
          </p>
        </div>
      </div>
    </ProjectShell>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
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
        {message.pending ? (
          <span className="text-ink-tertiary">Thinking…</span>
        ) : (
          <span className="whitespace-pre-wrap">{message.content}</span>
        )}
      </div>
    </div>
  );
}

function AiContextRail({ projectId }: { projectId: string }) {
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
            <RailRow
              label="Documents"
              value={String(project?.documentCount ?? 0)}
            />
            <RailRow
              label="Queries"
              value={String(project?.queryCount ?? 0)}
            />
            <RailRow label="Cross-project" value="off" />
          </dl>
        </Section>
        <Section title="Scope">
          <div className="flex flex-wrap gap-1.5">
            <Badge tone="brand">All tables</Badge>
            <Badge tone="neutral">Project documents</Badge>
          </div>
        </Section>
      </div>
    </aside>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
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
