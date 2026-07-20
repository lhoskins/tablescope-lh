"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  IconArrowUp,
  IconPlus,
  IconSparkles,
  IconMessage,
  IconExternalLink,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { TurnBubble } from "@/components/tablescope/conversation/conversation-turn";
import {
  createConversation,
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

interface ProjectOverviewChatProps {
  projectId: string;
}

function useAutosize(
  ref: React.RefObject<HTMLTextAreaElement | null>,
  value: string,
  minRows = 2,
  maxRows = 8,
) {
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof window === "undefined") return;

    const computed = window.getComputedStyle(el);
    const lineHeightStr = computed.lineHeight;
    const lineHeight =
      lineHeightStr === "normal"
        ? parseFloat(computed.fontSize) * 1.2
        : parseFloat(lineHeightStr);

    const minHeight = minRows * lineHeight;
    const maxHeight = maxRows * lineHeight;

    el.style.overflow = "hidden";
    el.style.height = "auto";
    const nextHeight = Math.max(el.scrollHeight, minHeight);
    if (nextHeight > maxHeight) {
      el.style.height = `${maxHeight}px`;
      el.style.overflowY = "auto";
    } else {
      el.style.height = `${nextHeight}px`;
      el.style.overflowY = "hidden";
    }
  }, [ref, value, minRows, maxRows]);
}

export function ProjectOverviewChat({ projectId }: ProjectOverviewChatProps) {
  const router = useRouter();
  const projectIdNum = Number(projectId);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasResumed, setHasResumed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [isComposing, setIsComposing] = useState(false);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);

  useAutosize(textareaRef, input, 2, 8);

  const loadConversations = useCallback(async () => {
    try {
      const data = await listConversations(projectIdNum);
      setConversations(data);
      return data;
    } catch {
      return [] as ConversationSummary[];
    }
  }, [projectIdNum]);

  useEffect(() => {
    let cancelled = false;
    async function resume() {
      const data = await loadConversations();
      if (cancelled) return;
      if (data.length > 0 && !hasResumed) {
        setHasResumed(true);
        try {
          const full = await getConversation(data[0].id);
          if (!cancelled) setConversation(full);
        } catch (err) {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : "Could not resume conversation.");
          }
        }
      }
    }
    void resume();
    return () => {
      cancelled = true;
    };
  }, [loadConversations, hasResumed]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [conversation?.turns, busy]);

  async function send(raw: string) {
    const message = raw.trim();
    if (!message || busy || isComposing) return;
    setPendingMessage(message);
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
        setPendingMessage(null);
        await loadConversations();
      } else {
        const updated = await submitTurn(conversation.id, { message });
        setPendingMessage(null);
        setConversation((prev) => {
          if (!prev) return prev;
          const turns = [...prev.turns, updated.turn];
          return { ...prev, turns, updated_at: new Date().toISOString() };
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setPendingMessage(null);
      setBusy(false);
    }
  }

  function startNew() {
    setConversation(null);
    setInput("");
    setError(null);
    setHasResumed(true);
  }

  const openInAssistant = () => {
    if (!conversation) return;
    router.push(`/projects/${projectId}/ai?conversation=${conversation.id}`);
  };

  const pendingQuestion = busy ? pendingMessage : null;

  return (
    <div className="space-y-3 rounded-xl border border-line-secondary bg-bg-primary p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-50 text-brand-500">
            <IconMessage size={16} />
          </div>
          <div>
            <h2 className="text-h3 text-ink-primary">Ask TableScope</h2>
            <p className="text-small text-ink-tertiary">
              Answers are grounded in this project and audited.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {conversation && (
            <Button variant="ghost" size="sm" onClick={openInAssistant}>
              <IconExternalLink size={14} />
              Open in AI Assistant
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={startNew}>
            <IconPlus size={14} />
            New chat
          </Button>
        </div>
      </div>

      {!conversation || conversation.turns.length === 0 ? (
        <div className="flex flex-wrap gap-2">
          {QUICK_PROMPTS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => void send(p)}
              disabled={busy}
              className="rounded-lg border border-line-tertiary bg-bg-secondary px-3 py-2 text-left text-[13px] text-ink-secondary hover:border-brand-500 hover:bg-brand-50/40 hover:text-ink-primary"
            >
              {p}
            </button>
          ))}
        </div>
      ) : null}

      {(conversation?.turns.length ?? 0) > 0 && (
        <div
          ref={scrollRef}
          className="max-h-[30rem] space-y-4 overflow-y-auto rounded-lg border border-line-tertiary bg-bg-secondary p-3"
        >
          {conversation!.turns.map((t, i) => (
            <TurnBubble
              key={t.id}
              turn={t}
              isLast={i === conversation!.turns.length - 1}
              onFollowUp={(text) => void send(text)}
            />
          ))}
          {pendingQuestion && (
            <div className="flex justify-end">
              <div className="max-w-[80%] rounded-lg bg-brand px-3.5 py-2.5 text-[13px] leading-relaxed text-brand-fg">
                {pendingQuestion}
              </div>
            </div>
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
      )}

      <div className="flex items-end gap-2 rounded-lg border border-line-secondary bg-bg-primary px-3 py-2">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onCompositionStart={() => setIsComposing(true)}
          onCompositionEnd={() => setIsComposing(false)}
          onKeyDown={(e) => {
            if (isComposing || e.nativeEvent.isComposing) return;
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(input);
            }
          }}
          rows={2}
          placeholder="Ask anything about this project…"
          aria-label="Ask anything about this project"
          disabled={busy}
          className={cn(
            "max-h-40 min-h-[40px] flex-1 resize-none bg-transparent text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:outline-none",
          )}
        />
        <button
          type="button"
          onClick={() => void send(input)}
          disabled={busy || !input.trim()}
          aria-label="Send"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-brand text-brand-fg hover:bg-brand-700 disabled:opacity-40"
        >
          <IconArrowUp size={15} />
        </button>
      </div>
    </div>
  );
}
