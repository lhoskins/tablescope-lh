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
import { useReportBuilder } from "@/lib/stores/report-builder-store";
import { formatLastUpdated } from "@/lib/format-datetime";
import { IntelligenceCard, LoadingCard } from "./intelligence-card";
import { IntelligenceSidebar } from "./intelligence-sidebar";
import { IntelligenceStrip } from "./intelligence-strip";
import { ReportBuilderPanel } from "./report-builder-panel";

type Status = "idle" | "streaming" | "complete" | "error";

function Section({
  title,
  icon,
  cards,
  onAdd,
}: {
  title: string;
  icon: React.ReactNode;
  cards: InsightCard[];
  onAdd: (card: InsightCard) => void;
}) {
  if (cards.length === 0) return null;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-h3 text-ink-secondary">
        {icon}
        <span>{title}</span>
        <span className="text-caption text-ink-tertiary">({cards.length})</span>
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {cards.map((card) => (
          <IntelligenceCard key={card.id} card={card} onAddToReport={onAdd} />
        ))}
      </div>
    </div>
  );
}

export function IntelligenceFeed() {
  const [status, setStatus] = useState<Status>("idle");
  const [projects, setProjects] = useState<StreamProject[]>([]);
  const [results, setResults] = useState<Record<string, ProjectResult>>({});
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  // Projects that reported in the CURRENT run (fresh), regardless of
  // foreground/background mode — drives the sidebar's per-project "Analyzing"
  // state during a refresh without touching the visible (buffered) cards.
  const [freshCompleted, setFreshCompleted] = useState<Set<string>>(new Set());
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
  const { openPanel, addInsightCard, sections } = useReportBuilder();

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
        setFreshCompleted((prev) => new Set(prev).add(projectId));
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
          setFreshCompleted((prev) => new Set(prev).add(projectId));
          if (!bg) {
            setCompleted((prev) => new Set(prev).add(projectId));
          }
        } else {
          setStatus("complete");
          setFreshCompleted(new Set(bufProjectsRef.current.map((p) => p.id)));
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
      setFreshCompleted(new Set());
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

  const handleToggle = (key: keyof IntelligenceSettings, value: boolean) => {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
    updatePreferences({ [key]: value }).catch(() => {
      /* keep optimistic value; will reconcile on next load */
    });
  };

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

  const empty =
    status === "complete" && allInsights.length === 0 && projects.length === 0;

  return (
    <div className="space-y-4">
      <IntelligenceStrip
        running={running}
        lastUpdatedLabel={formatLastUpdated(lastUpdated)}
        onRefresh={handleRefresh}
        granularity={granularity}
        onGranularityChange={handleGranularity}
      />

      <div className="flex gap-5">
        <div className="min-w-0 flex-1 space-y-6">
          {synthesis && (
            <div className="rounded-lg border border-brand/30 bg-ai-bg p-4">
              <div className="flex items-center gap-2 text-ai">
                <IconSparkles size={18} />
                <h3 className="text-h3">{synthesis.headline}</h3>
              </div>
              <p className="mt-1 text-body text-ink-secondary">
                {synthesis.body}
              </p>
            </div>
          )}

          <Section
            title="Risks"
            icon={<IconAlertTriangle size={16} className="text-warning" />}
            cards={risks}
            onAdd={addInsightCard}
          />
          <Section
            title="Trends"
            icon={<IconTrendingUp size={16} className="text-ink-secondary" />}
            cards={trends}
            onAdd={addInsightCard}
          />
          <Section
            title="Opportunities"
            icon={<IconBulb size={16} className="text-success" />}
            cards={opportunities}
            onAdd={addInsightCard}
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

        <IntelligenceSidebar
          projects={projects}
          results={results}
          completed={completed}
          refreshing={running}
          freshCompleted={freshCompleted}
          insights={allInsights}
          cardsInReport={sections.length}
          settings={settings}
          onStartReport={openPanel}
          onToggleSetting={handleToggle}
        />
      </div>

      <ReportBuilderPanel />
    </div>
  );
}
