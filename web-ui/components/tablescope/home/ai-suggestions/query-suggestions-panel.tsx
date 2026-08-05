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
import { getDefaultOptions } from "@/lib/visualizations/chartRegistry";import { ProjectHeader } from "./project-header";
import { EmptyState } from "./empty-state";
import { QuerySuggestionCard } from "./query-suggestion-card";



// ── Queries ──────────────────────────────────────────────────────────

export function QuerySuggestionsPanel({
  projects,
  showProjectHeader = true,
}: {
  projects: QuerySuggestionsProject[];
  showProjectHeader?: boolean;
}) {
  const withResults = projects.filter((p) => p.suggestions.length > 0);
  if (withResults.length === 0) {
    return (
      <EmptyState label="No query suggestions for your projects right now." />
    );
  }
  return (
    <div className="space-y-8">
      {withResults.map((p) => (
        <section key={p.projectId}>
          {showProjectHeader && (
            <ProjectHeader name={p.projectName} color={p.projectColor} />
          )}
          <div className="space-y-3">
            {p.suggestions.map((s, i) => (
              <QuerySuggestionCard
                key={i}
                projectId={Number(p.projectId)}
                title={s.title}
                description={s.description}
                sql={s.sql}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}