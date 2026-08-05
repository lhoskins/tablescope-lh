"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  clearBusinessInsightCache,
  getHomeIntelligenceRunStatus,
  getIntelligenceSnapshot,
  getPreferences,
  refreshHomeIntelligence,
  streamHomeIntelligence,
  updatePreferences,
  type CrossProjectSynthesis,
  type InsightCard,
  type IntelligenceEvent,
  type IntelligenceSettings,
  type IntelligenceSnapshot,
  type ProjectResult,
  type StreamProject,
} from "@/lib/api/home-intelligence";
import { useToasts } from "@/components/ui/toast";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";
import type { FilterableProject } from "./intelligence-strip";
import { EMPTY_PROJECTS } from "./intelligence-feed/empty-projects";

type ProjectSelection = {
  ids: Set<string>;
  allSelected: boolean;
};

type UseIntelligenceFeedStateProps = {
  onPin?: (card: InsightCard) => void;
  onCreateAction?: (card: InsightCard) => void;
  availableProjects?: FilterableProject[];
};

export function useIntelligenceFeedState({
  onPin,
  onCreateAction,
  availableProjects: propAvailableProjects,
}: UseIntelligenceFeedStateProps = {}) {
  const availableProjects = useMemo(
    () =>
      propAvailableProjects && propAvailableProjects.length > 0
        ? propAvailableProjects
        : EMPTY_PROJECTS,
    [propAvailableProjects],
  );
  const { toasts, push: pushToast, dismiss } = useToasts();
  const [saveCard, setSaveCard] = useState<InsightCard | null>(null);
  const [status, setStatus] = useState<"idle" | "streaming" | "complete" | "error">("idle");
  const [projects, setProjects] = useState<StreamProject[]>([]);
  const [results, setResults] = useState<Record<string, ProjectResult>>({});
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  const [synthesis, setSynthesis] = useState<CrossProjectSynthesis | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [settings, setSettings] = useState<IntelligenceSettings | null>(null);
  const [, forceTick] = useState(0);
  const [, setStale] = useState(false);
  const [, setStaleProjectIds] = useState<string[]>([]);

  const [selection, setSelection] = useState<ProjectSelection>({
    ids: new Set(),
    allSelected: true,
  });

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
  const pollTimerRef = useRef<number | null>(null);
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
        startStream(intel.cross_project, intel.granularity ?? 3, hydrated);
      }
    });
    return () => {
      cancelled = true;
      controllerRef.current?.abort();
      if (pollTimerRef.current) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [startStream]);

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

  const visibleProjects = useMemo(
    () => projects.filter((p) => selectedProjectIds.has(p.id)),
    [projects, selectedProjectIds],
  );

  const pending = visibleProjects.filter((p) => !completed.has(p.id));
  const running = status === "streaming";

  const granularity = settings?.granularity ?? 3;

  const applySnapshot = useCallback((snap: IntelligenceSnapshot) => {
    setProjects(snap.projects);
    const map: Record<string, ProjectResult> = {};
    for (const r of snap.results) map[r.projectId] = r;
    setResults(map);
    visibleResultCountRef.current = Object.keys(map).length;
    setCompleted(new Set(Object.keys(map)));
    setSynthesis(snap.synthesis);
    setLastUpdated(snap.updatedAt ? new Date(snap.updatedAt) : new Date());
    setStale(Boolean(snap.stale));
    setStaleProjectIds(snap.staleProjects ?? []);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const handleRefresh = useCallback(
    (overrideGranularity?: number) => {
      controllerRef.current?.abort();
      stopPolling();
      setStatus("streaming");
      refreshHomeIntelligence({
        crossProject: settings?.cross_project ?? true,
        granularity: overrideGranularity ?? granularity,
      })
        .then((res) => {
          if (!res.run_id) {
            setStatus("complete");
            return;
          }
          getHomeIntelligenceRunStatus(res.run_id).then((status) => {
            if (status.complete) {
              getIntelligenceSnapshot().then((snapRes) => {
                const snap = snapRes.snapshot ?? null;
                if (snap) applySnapshot(snap);
                setStatus(snap?.stale ? "streaming" : "complete");
              });
            }
          });
          pollTimerRef.current = window.setInterval(() => {
            const check = async () => {
              if (res.run_id) {
                const status = await getHomeIntelligenceRunStatus(res.run_id).catch(
                  () => null,
                );
                if (!status?.complete) return;
              }
              const snapRes = await getIntelligenceSnapshot().catch(() => null);
              const snap = snapRes?.snapshot ?? null;
              if (snap) {
                applySnapshot(snap);
                if (!snap.stale) {
                  stopPolling();
                  setStatus("complete");
                }
              }
            };
            void check();
          }, 5000);
        })
        .catch(() => {
          setStatus("error");
        });
    },
    [applySnapshot, granularity, settings?.cross_project, stopPolling],
  );

  const handleGranularity = useCallback(
    (value: number) => {
      setSettings((prev) => (prev ? { ...prev, granularity: value } : prev));
      updatePreferences({ granularity: value }).catch(() => {
        /* keep optimistic value; will reconcile on next load */
      });
      handleRefresh(value);
    },
    [handleRefresh],
  );

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

  const selectedProjectIdsArray = useMemo(
    () => [...selectedProjectIds],
    [selectedProjectIds],
  );

  return {
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
    isAllSelected,
  };
}
