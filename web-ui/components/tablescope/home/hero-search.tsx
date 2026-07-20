"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { IconArrowUp, IconSparkles } from "@tabler/icons-react";
import { apiClient } from "@/lib/api-client";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";

interface RoutePromptResponse {
  route: string;
  prefilled: string;
}

export function HeroSearch({
  projectId,
}: {
  /** When set, prompts go straight to this project's AI assistant so the
   *  conversation is grounded in (and isolated to) that project's data. */
  projectId?: string | number;
} = {}) {
  const router = useRouter();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  async function submit(prompt: string) {
    const q = prompt.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    setError(null);
    if (projectId != null) {
      router.push(`/projects/${projectId}/ai?q=${encodeURIComponent(q)}`);
      return;
    }
    try {
      const res = await apiClient.post<RoutePromptResponse>(
        "/api/ai/route-prompt",
        { prompt: q },
      );
      const sep = res.route.includes("?") ? "&" : "?";
      router.push(`${res.route}${sep}q=${encodeURIComponent(res.prefilled)}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col items-center">
      <h1 className="text-display text-center text-ink-primary">
        What would you like to analyze?
      </h1>
      <p className="mt-2 text-center text-[15px] text-ink-secondary">
        Ask anything across your connected data, documents, and dashboards.
      </p>

      <div className="mt-6 w-full max-w-2xl">
        <div className="flex items-center gap-2 rounded-xl border border-line-secondary bg-bg-primary px-4 py-2.5 focus-within:border-brand-100 focus-within:ring-2 focus-within:ring-brand-100">
          <IconSparkles size={18} className="shrink-0 text-ai" />
          <AutosizeTextarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit(value);
              }
            }}
            minRows={1}
            maxRows={8}
            placeholder="Ask Tablescope anything…"
            aria-label="Ask Tablescope anything"
            className="min-w-0 flex-1 text-[14px] text-ink-primary placeholder:text-ink-tertiary"
          />
          <button
            type="button"
            onClick={() => void submit(value)}
            disabled={submitting || !value.trim()}
            aria-label="Ask"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand text-brand-fg hover:bg-brand-700 disabled:opacity-50"
          >
            <IconArrowUp size={16} />
          </button>
        </div>
        {error && <p className="mt-2 text-center text-small text-danger">{error}</p>}
      </div>
    </div>
  );
}
