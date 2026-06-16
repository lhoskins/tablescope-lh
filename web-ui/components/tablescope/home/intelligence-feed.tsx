"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IconAlertTriangle,
  IconBulb,
  IconSparkles,
  IconTrendingUp,
} from "@tabler/icons-react";
import {
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
import { IntelligenceCard, LoadingCard } from "./intelligence-card";
import { IntelligenceSidebar } from "./intelligence-sidebar";
import { IntelligenceStrip } from "./intelligence-strip";
import { ReportBuilderPanel } from "./report-builder-panel";

type Status = "idle" | "streaming" | "complete" | "error";

function timeAgoLabel(date: Date | null): string | null {
  if (!date) return null;
  const mins = Math.floor((Date.now() - date.getTime()) / 60000);
  if (mins < 1) return "Updated just now";
  if (mins === 1) return "Updated 1m ago";
  if (mins < 60) return `Updated ${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `Updated ${hrs}h ago`;
}

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
      <div className="space-y-3">
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
  const [synthesis, setSynthesis] = useState<CrossProjectSynthesis | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [settings, setSettings] = useState<IntelligenceSettings | null>(null);
  const [, forceTick] = useState(0);

  const controllerRef = useRef<AbortController | null>(null);
  const { openPanel, addInsightCard, sections } = useReportBuilder();

  const handleEvent = useCallback((event: IntelligenceEvent) => {
    switch (event.type) {
      case "start":
        setProjects(event.projects);
        break;
      case "project_complete": {
        const { projectId, projectName, projectColor, insights } = event;
        setResults((prev) => ({
          ...prev,
          [projectId]: { projectId, projectName, projectColor, insights },
        }));
        setCompleted((prev) => new Set(prev).add(projectId));
        setLastUpdated(new Date());
        break;
      }
      case "project_error":
        setErrorMsg(event.error);
        break;
      case "synthesis_complete":
        setSynthesis(event.synthesis);
        break;
      case "done":
        setStatus("complete");
        setLastUpdated(new Date());
        break;
    }
  }, []);

  const startStream = useCallback(
    (crossProject: boolean, granularity: number) => {
      controllerRef.current?.abort();
      setStatus("streaming");
      setProjects([]);
      setResults({});
      setCompleted(new Set());
      setSynthesis(null);
      setErrorMsg(null);
      controllerRef.current = streamHomeIntelligence(handleEvent, {
        crossProject,
        granularity,
      });
    },
    [handleEvent],
  );

  // Load settings, then auto-run if enabled.
  useEffect(() => {
    let cancelled = false;
    getPreferences()
      .then((prefs) => {
        if (cancelled) return;
        setSettings(prefs.intelligence);
        if (prefs.intelligence.run_on_load) {
          startStream(
            prefs.intelligence.cross_project,
            prefs.intelligence.granularity ?? 3,
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          // Fall back to running with defaults if prefs can't load.
          setSettings({
            run_on_load: true,
            cross_project: true,
            email_digest: false,
            granularity: 3,
          });
          startStream(true, 3);
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
      c.severity === "urgent",
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

  const handleGranularity = (value: number) => {
    setSettings((prev) => (prev ? { ...prev, granularity: value } : prev));
    updatePreferences({ granularity: value }).catch(() => {
      /* keep optimistic value; will reconcile on next load */
    });
    startStream(settings?.cross_project ?? true, value);
  };

  const empty =
    status === "complete" && allInsights.length === 0 && projects.length === 0;

  return (
    <div className="space-y-4">
      <IntelligenceStrip
        projectCount={projects.length}
        insights={allInsights}
        running={running}
        lastUpdatedLabel={timeAgoLabel(lastUpdated)}
        onRefresh={() => startStream(settings?.cross_project ?? true, granularity)}
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

          {errorMsg && (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger/10 p-4">
              <div className="flex items-center gap-2 text-small text-danger">
                <IconAlertTriangle size={16} />
                <span>AI intelligence hit an error: {errorMsg}</span>
              </div>
              <button
                type="button"
                onClick={() =>
                  startStream(settings?.cross_project ?? true, granularity)
                }
                className="rounded-md border border-danger/40 px-2.5 py-1 text-small font-medium text-danger hover:bg-danger/10"
              >
                Retry
              </button>
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
            projects.length > 0 &&
            !errorMsg && (
              <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
                No actionable insights surfaced across your projects right now.
              </div>
            )}
        </div>

        <IntelligenceSidebar
          projects={projects}
          results={results}
          completed={completed}
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
