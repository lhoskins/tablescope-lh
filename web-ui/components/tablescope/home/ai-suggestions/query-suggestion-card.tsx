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
import { getDefaultOptions } from "@/lib/visualizations/chartRegistry";


export function QuerySuggestionCard({
  projectId,
  title,
  description,
  sql,
}: {
  projectId: number;
  title: string;
  description: string;
  sql: string;
}) {
  const [preview, setPreview] = useState(false);
  const [saved, setSaved] = useState(false);

  return (
    <article className="rounded-lg border border-line-tertiary bg-bg-primary p-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-body font-medium text-ink-primary">{title}</h4>
          {description && (
            <p className="mt-0.5 text-small text-ink-secondary">{description}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setPreview(true)}
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1 text-small font-medium transition-colors",
            saved
              ? "border-success/40 bg-success/10 text-success"
              : "border-line-secondary text-ink-secondary hover:border-brand-100 hover:text-brand-700",
          )}
        >
          {saved ? (
            <>
              <IconCheck size={14} /> Saved
            </>
          ) : (
            <>
              <IconPlayerPlay size={14} /> Preview
            </>
          )}
        </button>
      </header>
      <pre className="mt-3 overflow-x-auto rounded-md bg-bg-secondary p-3 text-caption text-ink-secondary">
        <code>{sql}</code>
      </pre>
      <QuerySuggestionPreviewModal
        open={preview}
        projectId={projectId}
        title={title}
        description={description}
        sql={sql}
        onClose={() => setPreview(false)}
        onSaved={() => setSaved(true)}
      />
    </article>
  );
}