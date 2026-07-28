"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IconAlertTriangle,
  IconBulb,
  IconChartBar,
  IconRefresh,
  IconTrash,
  IconTrendingUp,
} from "@tabler/icons-react";
import {
  clearBusinessInsightCache,
  getIntelligenceSnapshot,
  getPreferences,
  streamHomeIntelligence,
  updatePreferences,
  type CrossProjectSynthesis,
  type InsightCard,
  type IntelligenceEvent,
  type IntelligenceSettings,
  type ProjectResult,
  type StreamProject,
} from "@/lib/api/home-intelligence";
import { SaveInsightToDashboardModal } from "./save-insight-to-dashboard-modal";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { formatLastUpdated } from "@/lib/format-datetime";
import { IntelligenceCard, LoadingCard } from "./intelligence-card";
import {
  useInsightFeedback,
  type SaveInsightFeedbackArgs,
} from "@/lib/hooks/use-insight-feedback";
import type { GovernanceItem, InsightFeedbackRecord } from "@/lib/api/insight-feedback";
import { IntelligenceStrip, type FilterableProject } from "./intelligence-strip";
import {
  InsightPanel,
  PanelEmpty,
} from "@/components/tablescope/insight-panel";
import {
  insightAnchorId,
  useReturnTarget,
  useScrollToReturnTarget,
} from "@/lib/insights/return-target";
import { PercentChangeSummaryPanel } from "./percent-change-summary-panel";

type Status = "idle" | "streaming" | "complete" | "error";

function pinFingerprintKey(card: InsightCard): string | undefined {
  return (
    card.evidenceFingerprint?.resultFingerprint ??
    card.insightId ??
    card.id ??
    undefined
  );
}

function Section({
  title,
  icon,
  cards,
  emptyText,
  loading,
  defaultOpen,
  feedbackById,
  savingFeedback,
  onSaveToDashboard,
  onPin,
  pinnedByFingerprint,
  onFeedbackSave,
  onFeedbackRemove,
  onFeedbackRespond,
  governanceById,
  onCreateAction,
  actionsDisclosure = "collapsible",
}: {
  title: string;
  icon: React.ReactNode;
  cards: InsightCard[];
  emptyText: string;
  loading: boolean;
  defaultOpen?: boolean;
  feedbackById: Record<string, InsightFeedbackRecord>;
  savingFeedback: boolean;
  onSaveToDashboard?: (card: InsightCard) => void;
  onPin?: (card: InsightCard) => void;
  pinnedByFingerprint?: Map<string, number>;
  onFeedbackSave?: (card: InsightCard, payload: Omit<SaveInsightFeedbackArgs, "insightId" | "projectId" | "insightType" | "cardSnapshot" | "explanationSnapshot">) => void;
  onFeedbackRemove?: (card: InsightCard) => void;
  onFeedbackRespond?: (card: InsightCard, response: string) => void;
  governanceById?: Record<string, GovernanceItem>;
  onCreateAction?: (card: InsightCard) => void;
  actionsDisclosure?: "always-visible" | "collapsible";
}) {
  // A reader returning from a card's full analysis must find that card, so the
  // panel holding it opens regardless of its usual default.
  const returnTarget = useReturnTarget();
  const holdsReturnTarget =
    returnTarget != null &&
    cards.some((c) => (c.insightId || c.id) === returnTarget);

  return (
    <InsightPanel
      title={title}
      icon={icon}
      collapsible
      defaultOpen={defaultOpen || holdsReturnTarget}
      forceOpen={holdsReturnTarget}
      count={cards.length}
    >
      {cards.length === 0 ? (
        loading ? null : <PanelEmpty text={emptyText} />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {cards.map((card) => {
            const key = pinFingerprintKey(card) || card.insightId || card.id;
            const isPinned = Boolean(
              pinnedByFingerprint && key && pinnedByFingerprint.has(key),
            );
            const anchor = card.insightId || card.id;
            return (
              <div
                key={key}
                id={anchor ? insightAnchorId(anchor) : undefined}
                className="scroll-mt-24 rounded-lg transition-shadow data-[returned=true]:ring-2 data-[returned=true]:ring-brand-500"
              >
              <IntelligenceCard
                card={card}
                pinned={isPinned}
                feedback={feedbackById[card.insightId || card.id]}
                savingFeedback={savingFeedback}
                onSaveToDashboard={onSaveToDashboard}
                onPin={onPin}
                onFeedbackSave={
                  onFeedbackSave
                    ? (payload) => onFeedbackSave(card, payload)
                    : undefined
                }
                onFeedbackRemove={
                  onFeedbackRemove ? () => onFeedbackRemove(card) : undefined
                }
                onFeedbackRespond={
                  onFeedbackRespond ? (response) => onFeedbackRespond(card, response) : undefined
                }
                governance={governanceById?.[card.insightId || card.id]}
                onCreateAction={onCreateAction ? () => onCreateAction(card) : undefined}
                actionsDisclosure={actionsDisclosure}
              />
              </div>
            );
          })}
        </div>
      )}
    </InsightPanel>
  );
}

export interface IntelligenceFeedProps {
  onPin?: (card: InsightCard) => void;
  pinnedByFingerprint?: Map<string, number>;
  onCreateAction?: (card: InsightCard) => void;
  /** Accessible projects used to populate the filter and default selection. */
  availableProjects?: FilterableProject[];
}

const EMPTY_PROJECTS: FilterableProject[] = [];

export function IntelligenceFeed({
  onPin,
  pinnedByFingerprint,
  onCreateAction,
  availableProjects: propAvailableProjects,
}: IntelligenceFeedProps = {}) {
  // Normalize the accessible project list to a stable reference so the filter
  // state and memoized derived lists don't churn when the parent passes a new
  // empty array each render while loading.
  const availableProjects = useMemo(
    () =>
      propAvailableProjects && propAvailableProjects.length > 0
        ? propAvailableProjects
        : EMPTY_PROJECTS,
    [propAvailableProjects],
  );
  const { toasts, push: pushToast, dismiss } = useToasts();
  const [saveCard, setSaveCard] = useState<InsightCard | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [projects, setProjects] = useState<StreamProject[]>([]);
  const [results, setResults] = useState<Record<string, ProjectResult>>({});
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  const [synthesis, setSynthesis] = useState<CrossProjectSynthesis | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [settings, setSettings] = useState<IntelligenceSettings | null>(null);
  const [, forceTick] = useState(0);
  const [stale, setStale] = useState(false);
  const [staleProjectIds, setStaleProjectIds] = useState<string[]>([]);

  interface ProjectSelection {
    ids: Set<string>;
    allSelected: boolean;
  }

  const [selection, setSelection] = useState<ProjectSelection>({
    ids: new Set(),
    allSelected: true,
  });

  // Build the authoritative list of filterable projects from the accessible
  // project list and from any projects already present in the stream/snapshot.
  const knownProjects = useMemo<FilterableProject[]>(() => {
    const map = new Map<string, FilterableProject>();
    for (const p of availableProjects) map.set(p.id, p);
    for (const p of projects) {
      if (!map.has(p.id)) {
        map.set(p.id, { id: p.id, name: p.name, accent: p.color });
      }
    }
    for (const [id, r] of Object.entries(results)) {
      if (!map.has(id)) {
        map.set(id, { id, name: r.projectName, accent: r.projectColor });
      }
    }
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [availableProjects, projects, results]);

  const availableProjectIds = useMemo(
    () => new Set(knownProjects.map((p) => p.id)),
    [knownProjects],
  );

  // Reconcile the selection when the project list changes. Keep the
  // all-selected state expanded to include newly discovered projects; otherwise
  // preserve the user's explicit subset.
  useEffect(() => {
    if (availableProjectIds.size === 0) return;
    setSelection((prev) => {
      if (prev.allSelected) return { ...prev, ids: new Set(availableProjectIds) };
      return {
        ...prev,
        ids: new Set([...prev.ids].filter((id) => availableProjectIds.has(id))),
      };
    });
  }, [availableProjectIds]);

  const selectedProjectIds = useMemo<Set<string>>(() => {
    if (
      selection.allSelected &&
      availableProjectIds.size > 0 &&
      selection.ids.size === 0
    ) {
      return availableProjectIds;
    }
    return selection.ids;
  }, [selection, availableProjectIds]);

  const isAllSelected = useMemo(
    () =>
      availableProjectIds.size > 0 &&
      availableProjectIds.size === selectedProjectIds.size &&
      [...availableProjectIds].every((id) => selectedProjectIds.has(id)),
    [availableProjectIds, selectedProjectIds],
  );

  const toggleProject = useCallback((id: string) => {
    setSelection((prev) => {
      const nextIds = new Set(prev.ids);
      if (nextIds.has(id)) nextIds.delete(id);
      else nextIds.add(id);
      const allSelected =
        availableProjectIds.size > 0 &&
        [...availableProjectIds].every((pid) => nextIds.has(pid));
      return { ids: nextIds, allSelected };
    });
  }, [availableProjectIds]);

  const selectAllProjects = useCallback(() => {
    setSelection({ ids: new Set(availableProjectIds), allSelected: true });
  }, [availableProjectIds]);

  const clearProjects = useCallback(() => {
    setSelection({ ids: new Set(), allSelected: false });
  }, []);

  const controllerRef = useRef<AbortController | null>(null);
  // Background re-run accumulates into these buffers and commits at "done" so
  // the visible (saved-snapshot) cards never flicker mid-refresh.
  const backgroundRef = useRef(false);
  const bufProjectsRef = useRef<StreamProject[]>([]);
  const bufResultsRef = useRef<Record<string, ProjectResult>>({});
  const bufErroredRef = useRef<Set<string>>(new Set());
  const bufSynthesisRef = useRef<CrossProjectSynthesis | null>(null);
  const visibleResultCountRef = useRef(0);

  const handleEvent = useCallback((event: IntelligenceEvent) => {
    const bg = backgroundRef.current;
    switch (event.type) {
      case "start":
        bufProjectsRef.current = event.projects;
        bufResultsRef.current = {};
        bufErroredRef.current = new Set();
        bufSynthesisRef.current = null;
        if (!bg) {
          setProjects(event.projects);
          setResults({});
          visibleResultCountRef.current = 0;
          setCompleted(new Set());
          setSynthesis(null);
        }
        break;
      case "project_complete": {
        const { projectId, projectName, projectColor, insights } = event;
        bufResultsRef.current[projectId] = {
          projectId,
          projectName,
          projectColor,
          insights,
        };
        if (!bg) {
          setResults((prev) => ({
            ...prev,
            [projectId]: { projectId, projectName, projectColor, insights },
          }));
          visibleResultCountRef.current = Object.keys(bufResultsRef.current).length;
          setCompleted((prev) => new Set(prev).add(projectId));
          setLastUpdated(new Date());
        }
        break;
      }
      case "project_error": {
        const projectId = event.projectId;
        if (projectId) {
          bufErroredRef.current.add(projectId);
          if (!bg) {
            setCompleted((prev) => new Set(prev).add(projectId));
          }
        } else {
          setStatus("complete");
          if (!bg) {
            setCompleted(new Set(bufProjectsRef.current.map((p) => p.id)));
          }
        }
        break;
      }
      case "synthesis_complete":
        bufSynthesisRef.current = event.synthesis;
        if (!bg) setSynthesis(event.synthesis);
        break;
      case "done":
        if (bg) {
          const nextCount = Object.keys(bufResultsRef.current).length;
          const shouldReplace =
            nextCount > 0 && nextCount >= visibleResultCountRef.current;
          if (shouldReplace) {
            setProjects(bufProjectsRef.current);
            setResults({ ...bufResultsRef.current });
            visibleResultCountRef.current = nextCount;
            setCompleted(
              new Set([
                ...Object.keys(bufResultsRef.current),
                ...bufErroredRef.current,
              ]),
            );
            setSynthesis(bufSynthesisRef.current);
          }
        }
        setStatus("complete");
        if (Object.keys(bufResultsRef.current).length > 0) {
          setLastUpdated(new Date());
        }
        break;
    }
  }, []);

  const startStream = useCallback(
    (crossProject: boolean, granularity: number, background = false) => {
      controllerRef.current?.abort();
      backgroundRef.current = background;
      setStale(false);
      setStatus("streaming");
      if (!background) {
        setProjects([]);
        setResults({});
        setCompleted(new Set());
        setSynthesis(null);
      }
      controllerRef.current = streamHomeIntelligence(handleEvent, {
        crossProject,
        granularity,
      });
    },
    [handleEvent],
  );

  // Hydrate from the saved snapshot, then auto re-run in the background.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getPreferences().catch(() => null),
      getIntelligenceSnapshot().catch(() => null),
    ]).then(([prefs, snapRes]) => {
      if (cancelled) return;
      const intel: IntelligenceSettings = prefs?.intelligence ?? {
        run_on_load: true,
        cross_project: true,
        email_digest: false,
        granularity: 3,
      };
      setSettings(intel);

      const snap = snapRes?.snapshot ?? null;
      setStale(Boolean(snap?.stale));
      setStaleProjectIds(snap?.staleProjects ?? []);
      let hydrated = false;
      if (snap && snap.results.length > 0) {
        setProjects(snap.projects);
        const map: Record<string, ProjectResult> = {};
        for (const r of snap.results) map[r.projectId] = r;
        setResults(map);
        visibleResultCountRef.current = Object.keys(map).length;
        setCompleted(new Set(Object.keys(map)));
        setSynthesis(snap.synthesis);
        setLastUpdated(snap.updatedAt ? new Date(snap.updatedAt) : new Date());
        setStatus("complete");
        hydrated = true;
      }

      if (intel.run_on_load) {
        // If we showed a saved snapshot, refresh quietly in the background.
        startStream(intel.cross_project, intel.granularity ?? 3, hydrated);
      }
    });
    return () => {
      cancelled = true;
      controllerRef.current?.abort();
    };
  }, [startStream]);

  // Keep the "Updated Xm ago" label fresh.
  useEffect(() => {
    const t = setInterval(() => forceTick((n) => n + 1), 30000);
    return () => clearInterval(t);
  }, []);

  const allInsights = useMemo(
    () =>
      Object.values(results)
        .filter((r) => selectedProjectIds.has(r.projectId))
        .flatMap((r) => r.insights),
    [results, selectedProjectIds],
  );

  const insightIds = useMemo(
    () => allInsights.map((c) => c.insightId || c.id),
    [allInsights],
  );
  const {
    feedbackById,
    governanceById,
    saveFeedback,
    removeFeedback,
    respondToReview,
    saving: savingFeedback,
  } = useInsightFeedback(insightIds);

  const handleFeedbackSave = useCallback(
    (
      card: InsightCard,
      payload: {
        sentiment: "agree" | "disagree";
        reason_codes: string[];
        comment: string;
      },
    ) => {
      const insightId = card.insightId || card.id;
      if (!card.projectId || !insightId) return;
      void saveFeedback({
        insightId,
        projectId: Number(card.projectId),
        insightType: card.insightType,
        sentiment: payload.sentiment,
        reason_codes: payload.reason_codes,
        comment: payload.comment,
        cardSnapshot: card as unknown as Record<string, unknown>,
        explanationSnapshot: card.explanation as unknown as Record<string, unknown> | undefined,
      });
    },
    [saveFeedback],
  );

  const handleFeedbackRemove = useCallback(
    (card: InsightCard) => {
      const insightId = card.insightId || card.id;
      if (!card.projectId || !insightId) return;
      void removeFeedback({
        insightId,
        projectId: Number(card.projectId),
      });
    },
    [removeFeedback],
  );

  const handleFeedbackRespond = useCallback(
    (card: InsightCard, response: string) => {
      const insightId = card.insightId || card.id;
      if (!insightId) return;
      void respondToReview({ insightId, response });
    },
    [respondToReview],
  );

  const risks = allInsights.filter(
    (c) =>
      c.insightType.startsWith("risk_") ||
      c.severity === "critical" ||
      c.severity === "urgent" ||
      c.severity === "warning",
  );
  const trends = allInsights.filter(
    (c) => c.insightType.startsWith("trend_") && !risks.includes(c),
  );
  const opportunities = allInsights.filter(
    (c) =>
      (c.insightType.startsWith("opportunity_") ||
        c.severity === "opportunity") &&
      !risks.includes(c) &&
      !trends.includes(c),
  );
  const analysis = allInsights.filter(
    (c) =>
      !risks.includes(c) && !trends.includes(c) && !opportunities.includes(c),
  );

  const visibleProjects = useMemo(
    () => projects.filter((p) => selectedProjectIds.has(p.id)),
    [projects, selectedProjectIds],
  );

  const pending = visibleProjects.filter((p) => !completed.has(p.id));
  const running = status === "streaming";

  const granularity = settings?.granularity ?? 3;
  const hasCards = allInsights.length > 0;

  // Bring the card a reader came back to into view, once the feed has rendered
  // it. The browser's own hash scrolling fires before the cards exist.
  useScrollToReturnTarget(useReturnTarget(), hasCards);

  const handleGranularity = (value: number) => {
    setSettings((prev) => (prev ? { ...prev, granularity: value } : prev));
    updatePreferences({ granularity: value }).catch(() => {
      /* keep optimistic value; will reconcile on next load */
    });
    // Keep the current cards visible until the new run finishes.
    startStream(settings?.cross_project ?? true, value, hasCards);
  };

  const handleRefresh = () => {
    startStream(settings?.cross_project ?? true, granularity, hasCards);
  };

  const [clearingCache, setClearingCache] = useState(false);
  const handleClearCache = useCallback(async () => {
    if (clearingCache) return;
    if (!window.confirm("Clear all cached Business Insight cards?")) return;
    setClearingCache(true);
    controllerRef.current?.abort();
    try {
      await clearBusinessInsightCache();
      setProjects([]);
      setResults({});
      setCompleted(new Set());
      setSynthesis(null);
      setLastUpdated(null);
      setStatus("idle");
      pushToast("Business Insight cache cleared", "success");
    } catch (err) {
      pushToast(`Failed to clear cache: ${String(err)}`, "error");
    } finally {
      setClearingCache(false);
    }
  }, [clearingCache, pushToast]);

  const handleSaveToDashboard = useCallback((card: InsightCard) => {
    setSaveCard(card);
  }, []);

  const handleSaved = useCallback(
    (_dashboardId: number, dashboardName: string) => {
      pushToast(`Saved to dashboard "${dashboardName}"`, "success");
      setSaveCard(null);
    },
    [pushToast],
  );

  const empty =
    status === "complete" &&
    allInsights.length === 0 &&
    visibleProjects.length === 0;

  return (
    <div className="space-y-4">
      <IntelligenceStrip
        projectCount={selectedProjectIds.size}
        totalProjectCount={availableProjectIds.size}
        running={running}
        lastUpdatedLabel={formatLastUpdated(lastUpdated)}
        onRefresh={handleRefresh}
        onClearCache={handleClearCache}
        isClearingCache={clearingCache}
        granularity={granularity}
        onGranularityChange={handleGranularity}
        availableProjects={knownProjects}
        selectedProjectIds={selectedProjectIds}
        onToggleProject={toggleProject}
        onSelectAll={selectAllProjects}
        onClear={clearProjects}
      />

      {synthesis && selectedProjectIds.size > 0 &&
        synthesis.projectIds &&
        synthesis.projectIds.length === selectedProjectIds.size &&
        synthesis.projectIds.every((id) => selectedProjectIds.has(id)) && (
        <div className="rounded-md border border-line-tertiary bg-bg-primary p-3 text-[13px] text-ink-secondary">
          <p className="font-medium text-ink-primary">{synthesis.headline}</p>
          <p className="mt-1">{synthesis.body}</p>
        </div>
      )}

      <div className="space-y-6">
        {selectedProjectIds.size === 0 && knownProjects.length > 0 ? (
          <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
            Select one or more projects to view Business Insights.
          </div>
        ) : (
          <>
            <Section
              title="Risks"
              icon={<IconAlertTriangle size={16} className="text-warning" />}
              cards={risks}
              defaultOpen={false}
              emptyText="No risks detected from your projects yet."
              loading={running}
              feedbackById={feedbackById}
              savingFeedback={savingFeedback}
              onSaveToDashboard={handleSaveToDashboard}
              onPin={onPin}
              pinnedByFingerprint={pinnedByFingerprint}
              onFeedbackSave={handleFeedbackSave}
              onFeedbackRemove={handleFeedbackRemove}
              onFeedbackRespond={handleFeedbackRespond}
              governanceById={governanceById}
              onCreateAction={onCreateAction}
            />
            <Section
              title="Trends"
              icon={<IconTrendingUp size={16} className="text-ink-secondary" />}
              cards={trends}
              defaultOpen={false}
              emptyText="No trends detected from your projects yet."
              loading={running}
              feedbackById={feedbackById}
              savingFeedback={savingFeedback}
              onSaveToDashboard={handleSaveToDashboard}
              onPin={onPin}
              pinnedByFingerprint={pinnedByFingerprint}
              onFeedbackSave={handleFeedbackSave}
              onFeedbackRemove={handleFeedbackRemove}
              onFeedbackRespond={handleFeedbackRespond}
              governanceById={governanceById}
              onCreateAction={onCreateAction}
            />
            <Section
              title="Opportunities"
              icon={<IconBulb size={16} className="text-success" />}
              cards={opportunities}
              defaultOpen={false}
              emptyText="No opportunities detected from your projects yet."
              loading={running}
              feedbackById={feedbackById}
              savingFeedback={savingFeedback}
              onSaveToDashboard={handleSaveToDashboard}
              onPin={onPin}
              pinnedByFingerprint={pinnedByFingerprint}
              onFeedbackSave={handleFeedbackSave}
              onFeedbackRemove={handleFeedbackRemove}
              onFeedbackRespond={handleFeedbackRespond}
              governanceById={governanceById}
              onCreateAction={onCreateAction}
            />
            <PercentChangeSummaryPanel
              projectIds={[...selectedProjectIds].map((id) => Number(id))}
              snapshotFingerprint={
                status === "complete" ? lastUpdated?.toISOString() ?? null : null
              }
            />
            <Section
              title="Deeper analysis"
              icon={<IconChartBar size={16} className="text-brand-500" />}
              cards={analysis}
              defaultOpen={false}
              emptyText="No additional analysis available."
              loading={running}
              feedbackById={feedbackById}
              savingFeedback={savingFeedback}
              onSaveToDashboard={handleSaveToDashboard}
              onPin={onPin}
              pinnedByFingerprint={pinnedByFingerprint}
              onFeedbackSave={handleFeedbackSave}
              onFeedbackRemove={handleFeedbackRemove}
              onFeedbackRespond={handleFeedbackRespond}
              governanceById={governanceById}
              onCreateAction={onCreateAction}
            />

            {pending.length > 0 && (
              <div className="space-y-3">
                {pending.map((p) => (
                  <LoadingCard key={p.id} projectName={p.name} />
                ))}
              </div>
            )}

            {empty && (
              <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
                No projects to analyze yet. Create a project and connect data to
                see AI intelligence here.
              </div>
            )}

            {status === "complete" &&
              allInsights.length === 0 &&
              visibleProjects.length > 0 && (
                <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
                  No new insights are available right now.
                </div>
              )}
          </>
        )}
      </div>

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
