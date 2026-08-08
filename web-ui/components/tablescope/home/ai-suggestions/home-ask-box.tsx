"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiClient } from "@/lib/api-client";
import { AskAnythingComposer } from "@/components/ai/ask-anything-composer";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { RoutePromptResponse } from "./route-prompt-response";



export function HomeAskBox({
  projectId,
  onAsk,
}: {
  projectId?: number;
  onAsk?: (prompt: string) => void | Promise<void>;
}) {
  const { data: identity } = useCurrentUser();
  const router = useRouter();
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(prompt: string) {
    const q = prompt.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      if (onAsk) {
        await onAsk(q);
        setValue("");
        return;
      }
      const res = await apiClient.post<RoutePromptResponse>(
        "/api/ai/route-prompt",
        { prompt: q, project_id: projectId ?? null },
      );
      const sep = res.route.includes("?") ? "&" : "?";
      router.push(`${res.route}${sep}q=${encodeURIComponent(res.prefilled)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ask failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-3 text-center">
      <div className="space-y-1">
        <h2 className="text-h2 text-ink-primary">
          What would you like to analyze?
        </h2>
        <p className="text-small text-ink-secondary">
          Ask anything across your connected data, documents, and dashboards
        </p>
      </div>
      <div className="mx-auto w-full max-w-2xl">
        <AskAnythingComposer
          value={value}
          onChange={setValue}
          onSubmit={submit}
          placeholder="Ask anything across your connected data, documents, and dashboards"
          ariaLabel="Ask anything across your connected data, documents, and dashboards"
          submitAriaLabel="Ask"
          busy={submitting}
          voiceEnabled={identity?.tenant.voiceInputEnabled ?? false}
          projectId={projectId}
        />
      </div>
      {error && <p className="text-small text-danger">{error}</p>}
    </div>
  );
}