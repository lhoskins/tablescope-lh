"use client";


import { useCallback, useState } from "react";
import {
  IconChartHistogram,
  IconLayoutDashboard,
  IconBulb,
  IconCheck,
  IconLoader2,
  IconDeviceFloppy,
  IconPlayerPlay,
  IconSparkles,
  IconArrowUp,
} from "@tabler/icons-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/api-client";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import {
  suggestQueries,
  suggestDashboards,
  suggestInsights,
  saveDashboardSuggestion,
  type QuerySuggestionsProject,
  type DashboardSuggestionsProject,
  type ProjectResult,
  type InsightCard,
} from "@/lib/api/home-intelligence";
import type {
  GovernanceItem,
  InsightFeedbackRecord,
} from "@/lib/api/insight-feedback";
import {
  IntelligenceCard,
  InsightChartBlock,
} from "@/components/tablescope/home/intelligence-card";
import { QuerySuggestionPreviewModal } from "@/components/tablescope/home/query-suggestion-preview-modal";
import { getDefaultOptions } from "@/lib/visualizations/chartRegistry";import { RoutePromptResponse } from "./route-prompt-response";



export function HomeAskBox({
  projectId,
  onAsk,
}: {
  projectId?: number;
  onAsk?: (prompt: string) => void | Promise<void>;
}) {
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
      <div className="mx-auto flex w-full max-w-2xl items-end gap-2 rounded-xl border border-line-secondary bg-bg-primary px-4 py-2.5 focus-within:border-brand-100 focus-within:ring-2 focus-within:ring-brand-100">
        <IconSparkles size={18} className="shrink-0 pb-1.5 text-ai" />
        <AutosizeTextarea
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
          placeholder="Ask anything across your connected data, documents, and dashboards"
          aria-label="Ask anything across your connected data, documents, and dashboards"
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
      {error && <p className="text-small text-danger">{error}</p>}
    </div>
  );
}