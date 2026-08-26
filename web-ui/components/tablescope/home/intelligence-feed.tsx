"use client";

import { formatLastUpdated } from "@/lib/format-datetime";
import { SaveInsightToDashboardModal } from "./save-insight-to-dashboard-modal";
import { LoadingCard } from "./intelligence-card";
import { ToastViewport } from "@/components/ui/toast";
import { IntelligenceWorkspace } from "@/components/tablescope/insights/intelligence-workspace";
import { useIntelligenceFeedState } from "./use-intelligence-feed-state";
import type { IntelligenceFeedProps } from "./intelligence-feed/intelligence-feed-props";

export function IntelligenceFeed({
  onPin,
  pinnedByFingerprint,
  onCreateAction,
  availableProjects: propAvailableProjects,
  actionsDisclosure,
  presentation = "default",
}: IntelligenceFeedProps = {}) {
  const state = useIntelligenceFeedState({
    onPin,
    onCreateAction,
    availableProjects: propAvailableProjects,
  });

  const {
    status,
    synthesis,
    selectedProjectIds,
    selectedProjectIdsArray,
    allInsights,
    visibleProjects,
    running,
    lastUpdated,
    knownProjects,
    availableProjectIds,
    granularity,
    clearingCache,
    saveCard,
    setSaveCard,
    toasts,
    dismiss,
    feedbackById,
    savingFeedback,
    governanceById,
    handleRefresh,
    handleClearCache,
    handleGranularity,
    handleSaveToDashboard,
    handleSaved,
    toggleProject,
    selectAllProjects,
    clearProjects,
    handleFeedbackSave,
    handleFeedbackRemove,
    handleFeedbackRespond,
    pending,
  } = state;

  const emptySelection =
    knownProjects.length > 0 ? (
      <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
        Select one or more projects to view Business Insights.
      </div>
    ) : null;

  const empty =
    status === "complete" && visibleProjects.length === 0 ? (
      <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
        No projects to analyze yet. Create a project and connect data to see AI
        intelligence here.
      </div>
    ) : null;

  const visibleSynthesis =
    synthesis &&
    selectedProjectIds.size > 0 &&
    synthesis.projectIds &&
    synthesis.projectIds.length === selectedProjectIds.size &&
    synthesis.projectIds.every((id) => selectedProjectIds.has(id))
      ? synthesis
      : null;

  return (
    <div className="space-y-4">
      {presentation === "default" && visibleSynthesis && (
        <div className="rounded-md border border-line-tertiary bg-bg-primary p-3 text-[13px] text-ink-secondary">
          <p className="font-medium text-ink-primary">
            {visibleSynthesis.headline}
          </p>
          <p className="mt-1">{visibleSynthesis.body}</p>
        </div>
      )}

      <IntelligenceWorkspace
        scope="business"
        projectIds={selectedProjectIdsArray.map((id) => Number(id))}
        cards={allInsights}
        running={running}
        lastUpdated={lastUpdated}
        snapshotFingerprint={status === "complete" ? lastUpdated?.toISOString() ?? null : null}
        toolbar={{
          projectCount: selectedProjectIds.size,
          totalProjectCount: availableProjectIds.size,
          running,
          lastUpdatedLabel: formatLastUpdated(lastUpdated),
          onRefresh: handleRefresh,
          onClearCache: handleClearCache,
          isClearingCache: clearingCache,
          granularity,
          onGranularityChange: handleGranularity,
          availableProjects: knownProjects,
          selectedProjectIds,
          onToggleProject: toggleProject,
          onSelectAll: selectAllProjects,
          onClear: clearProjects,
        }}
        actions={{
          onSaveToDashboard: handleSaveToDashboard,
          onPin,
          onCreateAction: onCreateAction,
          onFeedbackSave: handleFeedbackSave,
          onFeedbackRemove: handleFeedbackRemove,
          onFeedbackRespond: handleFeedbackRespond,
        }}
        feedback={{ feedbackById, savingFeedback, governanceById }}
        pinnedByFingerprint={pinnedByFingerprint}
        emptyMessages={{
          risks: "No risks detected from your projects yet.",
          trends: "No trends detected from your projects yet.",
          opportunities: "No opportunities detected from your projects yet.",
          analysis: "No additional analysis available.",
        }}
        emptySelection={emptySelection}
        empty={empty}
        actionsDisclosure={actionsDisclosure}
        presentation={presentation}
      />

      {pending.length > 0 && (
        <div className="space-y-3">
          {pending.map((p) => (
            <LoadingCard key={p.id} projectName={p.name} />
          ))}
        </div>
      )}

      {status === "complete" &&
        allInsights.length === 0 &&
        visibleProjects.length > 0 && (
        <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
          No new insights are available right now.
        </div>
      )}

      {saveCard && (
        <SaveInsightToDashboardModal
          card={saveCard}
          open={true}
          onClose={() => setSaveCard(null)}
          onSaved={handleSaved}
        />
      )}

      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
