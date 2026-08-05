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
import { getDefaultOptions } from "@/lib/visualizations/chartRegistry";import { HomeAiSuggestionsCardActions } from "./home-ai-suggestions-card-actions";
import { ProjectHeader } from "./project-header";
import { EmptyState } from "./empty-state";
import { pinFingerprintKey } from "./pin-fingerprint-key";



// ── Insights ─────────────────────────────────────────────────────────

export function InsightsPanel({
  projects,
  showProjectHeader = true,
  cardActions,
}: {
  projects: ProjectResult[];
  showProjectHeader?: boolean;
  cardActions?: HomeAiSuggestionsCardActions;
}) {
  const withResults = projects.filter((p) => p.insights.length > 0);
  if (withResults.length === 0) {
    return (
      <EmptyState label="No insights for your projects right now." />
    );
  }
  return (
    <div className="space-y-8">
      {withResults.map((p) => (
        <section key={p.projectId}>
          {showProjectHeader && (
            <ProjectHeader name={p.projectName} color={p.projectColor} />
          )}
          <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2">
            {p.insights.map((card) => {
              const key = pinFingerprintKey(card) || card.insightId || card.id;
              const isPinned = Boolean(
                cardActions?.pinnedByFingerprint &&
                  key &&
                  cardActions.pinnedByFingerprint.has(key),
              );
              const insightId = card.insightId || card.id;
              const feedback = insightId
                ? cardActions?.feedbackById?.[insightId]
                : undefined;
              const governance = insightId
                ? cardActions?.governanceById?.[insightId]
                : undefined;
              return (
                <IntelligenceCard
                  key={card.id}
                  card={card}
                  pinned={isPinned}
                  actionsDisclosure={cardActions?.actionsDisclosure}
                  onPin={cardActions?.onPin}
                  onSaveToDashboard={cardActions?.onSaveToDashboard}
                  onCreateAction={
                    cardActions?.onCreateAction
                      ? () => cardActions.onCreateAction!(card)
                      : undefined
                  }
                  onFeedbackSave={
                    cardActions?.onFeedbackSave
                      ? (payload) => cardActions.onFeedbackSave!(card, payload)
                      : undefined
                  }
                  onFeedbackRemove={
                    cardActions?.onFeedbackRemove
                      ? () => cardActions.onFeedbackRemove!(card)
                      : undefined
                  }
                  onFeedbackRespond={
                    cardActions?.onFeedbackRespond
                      ? (response) =>
                          cardActions.onFeedbackRespond!(card, response)
                      : undefined
                  }
                  feedback={feedback}
                  savingFeedback={cardActions?.savingFeedback}
                  governance={governance}
                />
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}