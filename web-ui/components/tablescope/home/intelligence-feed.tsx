"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IconAlertTriangle,
  IconBulb,
  IconSparkles,
  IconTrendingUp,
} from "@tabler/icons-react";
import {
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
import {
  IntelligenceCard,
  LoadingCard,
  renderBold,
  stripStars,
} from "./intelligence-card";
import {
  useInsightFeedback,
  type SaveInsightFeedbackArgs,
} from "@/lib/hooks/use-insight-feedback";
import type { InsightFeedbackRecord } from "@/lib/api/insight-feedback";
import { IntelligenceStrip } from "./intelligence-strip";
import {
  InsightPanel,
  PanelEmpty,
} from "@/components/tablescope/insight-panel";

type Status = "idle" | "streaming" | "complete" | "error";

function Section({
  title,
  icon,
  cards,
  emptyText,
  loading,
  feedbackById,
  savingFeedback,
  onSaveToDashboard,
  onPin,
  onFeedbackSave,
  onFeedbackRemove,
}: {
  title: string;
  icon: React.ReactNode;
  cards: InsightCard[];
  emptyText: string;
  loading: boolean;
  feedbackById: Record<string, InsightFeedbackRecord>;
  savingFeedback: boolean;
  onSaveToDashboard?: (card: InsightCard) => void;
  onPin?: (card: InsightCard) => void;
  onFeedbackSave?: (card: InsightCard, payload: Omit<SaveInsightFeedbackArgs, "insightId" | "projectId" | "insightType" | "cardSnapshot" | "explanationSnapshot">) => void;
  onFeedbackRemove?: (card: InsightCard) => void;
}) {
  return (
    <InsightPanel title={title} icon={icon} collapsible count={cards.length}>
      {cards.length === 0 ? (
        loading ? null : <PanelEmpty text={emptyText} />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {cards.map((card) => (
            <IntelligenceCard
              key={card.insightId || card.id}
              card={card}
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
            />
          ))}
        </div>
      )}
    </InsightPanel>
  );
}

export function IntelligenceFeed({ onPin }: { onPin?: (card: InsightCard) => void } = {}) {
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
    () => Object.values(results).flatMap((r) => r.insights),
    [results],
  );

  const insightIds = useMemo(
    () => allInsights.map((c) => c.insightId || c.id),
    [allInsights],
  );
  const {
    feedbackById,
    isLoading: feedbackLoading,
    saveFeedback,
    removeFeedback,
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

  const pending = projects.filter((p) => !completed.has(p.id));
  const running = status === "streaming";

  const granularity = settings?.granularity ?? 3;
  const hasCards = allInsights.length > 0;

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
    status === "complete" && allInsights.length === 0 && projects.length === 0;

  return (
    <div className="space-y-4">
      <IntelligenceStrip
        projectCount={projects.length}
        running={running}
        lastUpdatedLabel={formatLastUpdated(lastUpdated)}
        onRefresh={handleRefresh}
        granularity={granularity}
        onGranularityChange={handleGranularity}
        synthesisHeadline={synthesis ? stripStars(synthesis.headline) : null}
      />

      <div className="space-y-6">
        {synthesis?.body && (
          <div className="rounded-lg border border-brand/30 bg-ai-bg p-4">
            <div className="flex items-start gap-2 text-ai">
              <IconSparkles size={18} className="mt-0.5 shrink-0" />
              <p className="text-body text-ink-secondary">
                {renderBold(synthesis.body)}
              </p>
            </div>
          </div>
        )}

        <Section
          title="Risks"
          icon={<IconAlertTriangle size={16} className="text-warning" />}
          cards={risks}
          emptyText="No risks detected from your projects yet."
          loading={running}
          feedbackById={feedbackById}
          savingFeedback={savingFeedback}
          onSaveToDashboard={handleSaveToDashboard}
          onPin={onPin}
          onFeedbackSave={handleFeedbackSave}
          onFeedbackRemove={handleFeedbackRemove}
        />
        <Section
          title="Trends"
          icon={<IconTrendingUp size={16} className="text-ink-secondary" />}
          cards={trends}
          emptyText="No trends detected from your projects yet."
          loading={running}
          feedbackById={feedbackById}
          savingFeedback={savingFeedback}
          onSaveToDashboard={handleSaveToDashboard}
          onPin={onPin}
          onFeedbackSave={handleFeedbackSave}
          onFeedbackRemove={handleFeedbackRemove}
        />
        <Section
          title="Opportunities"
          icon={<IconBulb size={16} className="text-success" />}
          cards={opportunities}
          emptyText="No opportunities detected from your projects yet."
          loading={running}
          feedbackById={feedbackById}
          savingFeedback={savingFeedback}
          onSaveToDashboard={handleSaveToDashboard}
          onPin={onPin}
          onFeedbackSave={handleFeedbackSave}
          onFeedbackRemove={handleFeedbackRemove}
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
          projects.length > 0 && (
            <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
              No new insights are available right now.
            </div>
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
