"use client";


import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ResponsiveGridLayout,
  useContainerWidth,
  type EventCallback,
  type Layout,
  type LayoutItem,
  type ResponsiveLayouts,
} from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import {
  GRID_BREAKPOINTS,
  GRID_COLS,
  GRID_DRAG_CONFIG,
  GRID_MARGIN,
  GRID_RESIZE_CONFIG,
  GRID_ROW_HEIGHT,
  buildResponsiveHomeLayouts,
} from "@/lib/ui/grid-layout";
import {
  IconLoader2,
  IconRefresh,
} from "@tabler/icons-react";
import type { InsightCard } from "@/lib/api/home-intelligence";
import type { GovernanceItem, InsightFeedbackRecord } from "@/lib/api/insight-feedback";
import {
  deleteHomePin,
  getHomePins,
  refreshAllHomePins,
  updateHomePinLayout,
} from "@/lib/api/home-pins";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";
import {
  CreateActionFromInsightDialog,
  type ActionableInsight,
} from "@/components/tablescope/project-actions/create-action-from-insight-dialog";import { HomePinItem } from "./home-pins-grid/home-pin-item";
import { getPinInsightId } from "./home-pins-grid/get-pin-insight-id";
import { PinCard } from "./home-pins-grid/pin-card";



export function HomePinsGrid() {
  const queryClient = useQueryClient();
  const { data: pins = [], isLoading } = useQuery({
    queryKey: ["home-pins"],
    queryFn: getHomePins,
  });

  const insightCardPins = useMemo(
    () =>
      pins.filter(
        (p) =>
          p.pin_type === "insight_card" &&
          (p.frozen_payload ?? p.config)?.title,
      ),
    [pins],
  );
  const insightIds = useMemo(
    () => insightCardPins.map(getPinInsightId),
    [insightCardPins],
  );
  const {
    feedbackById,
    governanceById,
    saveFeedback,
    removeFeedback,
    respondToReview,
    saving: savingFeedback,
  } = useInsightFeedback(insightIds);

  const handleFeedbackSave = (
    pin: HomePinItem,
    payload: {
      sentiment: "agree" | "disagree";
      reason_codes: string[];
      comment: string;
    },
  ) => {
    const card = (pin.frozen_payload ?? pin.config ?? {}) as unknown as InsightCard;
    const insightId = card.insightId || card.id;
    const projectId = pin.project_id ?? Number(card.projectId);
    if (!insightId || !projectId) return;
    void saveFeedback({
      insightId,
      projectId,
      insightType: card.insightType,
      sentiment: payload.sentiment,
      reason_codes: payload.reason_codes,
      comment: payload.comment,
      cardSnapshot: card as unknown as Record<string, unknown>,
      explanationSnapshot: card.explanation as unknown as Record<string, unknown> | undefined,
    });
  };

  const { width: containerWidth, containerRef, mounted, measureWidth } =
    useContainerWidth({
      measureBeforeMount: true,
    });

  // Pins load after mount, so the container ref may not be present on the
  // initial measurement. Re-measure once pins arrive and the ref is attached.
  useEffect(() => {
    if (containerRef.current && pins.length > 0) {
      measureWidth();
    }
    // containerRef is a stable ref object and does not trigger re-runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pins.length, measureWidth]);

  const [currentBreakpoint, setCurrentBreakpoint] = useState<
    keyof typeof GRID_BREAKPOINTS
  >("lg");
  const [localLayouts, setLocalLayouts] = useState<ResponsiveLayouts | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [createActionOpen, setCreateActionOpen] = useState(false);
  const [selectedInsight, setSelectedInsight] = useState<ActionableInsight | null>(null);
  const [autoHeights, setAutoHeights] = useState<Record<string, number>>({});
  const [activePinId, setActivePinId] = useState<string | null>(null);

  const handleFeedbackRemove = (pin: HomePinItem) => {
    const card = (pin.frozen_payload ?? pin.config ?? {}) as unknown as InsightCard;
    const insightId = card.insightId || card.id;
    const projectId = pin.project_id ?? Number(card.projectId);
    if (!insightId || !projectId) return;
    void removeFeedback({ insightId, projectId });
  };

  const handleFeedbackRespond = (pin: HomePinItem, response: string) => {
    const card = (pin.frozen_payload ?? pin.config ?? {}) as unknown as InsightCard;
    const insightId = card.insightId || card.id;
    if (!insightId) return;
    void respondToReview({ insightId, response });
  };

  const handleCreateAction = (pin: HomePinItem) => {
    const card = (pin.frozen_payload ?? pin.config ?? {}) as unknown as InsightCard;
    if (!card.title || !card.projectId) return;
    const projectId = String(card.projectId ?? pin.project_id ?? "");
    const projectName = card.projectName ?? "";
    const insight: ActionableInsight = {
      insightId: card.insightId || card.id,
      insightType: card.insightType,
      title: card.title,
      summary: card.summary,
      severity: card.severity,
      projectId,
      projectName,
      recommendedAction: card.callout?.text || null,
      sources: card.sources,
      supportingSources: [
        ...(card.sources?.tables ?? []),
        ...(card.sources?.documents ?? []),
      ],
      explanation: card.explanation as Record<string, unknown> | undefined,
    };
    setSelectedInsight(insight);
    setCreateActionOpen(true);
  };

  const deleteMutation = useMutation({
    mutationFn: (pin: HomePinItem) => deleteHomePin(pin.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["home-pins"] }),
  });

  const refreshMutation = useMutation({
    mutationFn: () => refreshAllHomePins(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["home-pins"] }),
  });

  const layoutMutation = useMutation({
    mutationFn: (layout: LayoutItem[]) =>
      updateHomePinLayout(
        layout.map((l) => ({
          id: Number(l.i),
          grid_x: l.x,
          grid_y: l.y,
          grid_w: l.w,
          grid_h: l.h,
          position: l.y * 12 + l.x,
        })),
      ),
    onSuccess: () => {
      setLayoutError(null);
      queryClient.invalidateQueries({ queryKey: ["home-pins"] });
    },
    onError: () => {
      setLayoutError("Could not save layout");
      setLocalLayouts(null);
    },
  });

  const savedLayouts = useMemo(
    () => buildResponsiveHomeLayouts(pins),
    [pins],
  );

  const displayLayouts = useMemo(() => {
    if (localLayouts?.lg && localLayouts.lg.length === pins.length) {
      return localLayouts;
    }
    return savedLayouts;
  }, [localLayouts, savedLayouts, pins.length]);

  const measuredLayouts = useMemo<ResponsiveLayouts | null>(() => {
    if (!displayLayouts) return null;
    const result: ResponsiveLayouts = {};
    for (const bp of Object.keys(displayLayouts)) {
      const layout = displayLayouts[bp];
      if (!layout) continue;
      result[bp] = layout.map((item) => {
        const measured = autoHeights[item.i];
        if (typeof measured !== "number") return item;
        return { ...item, h: Math.max(item.h, measured), minH: measured };
      });
    }
    return result;
  }, [displayLayouts, autoHeights]);

  const handleHeightChange = useCallback(
    (pinId: string | number, rows: number) => {
      const key = String(pinId);
      setAutoHeights((prev) => (prev[key] === rows ? prev : { ...prev, [key]: rows }));
    },
    [],
  );

  // Reconcile optimistic layout with the server state once the saved layout
  // catches up to what we submitted.
  useEffect(() => {
    if (!localLayouts?.lg || layoutMutation.isPending) return;
    const saved = savedLayouts.lg;
    if (!saved || saved.length !== localLayouts.lg.length) return;

    const match = saved.every((item, idx) => {
      const local = localLayouts.lg![idx];
      return (
        local &&
        item.i === local.i &&
        item.x === local.x &&
        item.y === local.y &&
        item.w === local.w &&
        item.h === local.h
      );
    });

    if (match) {
      setLocalLayouts(null);
    }
  }, [savedLayouts, localLayouts, layoutMutation.isPending]);

  const handleLayoutChange = useCallback(
    (_layout: Layout, _allLayouts: ResponsiveLayouts) => {
      // Layout changes are committed only on drag/resize stop so we do not
      // overwrite the saved layout with intermediate compaction results.
      setLayoutError(null);
    },
    [],
  );

  const persistLayout = useCallback(
    (lg: LayoutItem[] | undefined) => {
      if (!lg || currentBreakpoint !== "lg") return;
      layoutMutation.mutate([...lg]);
    },
    [currentBreakpoint, layoutMutation],
  );

  const updateOptimisticLayouts = useCallback(
    (bpLayout: LayoutItem[]) => {
      setLocalLayouts((prev) => {
        const base = prev ?? savedLayouts;
        return { ...base, [currentBreakpoint]: [...bpLayout] };
      });
    },
    [currentBreakpoint, savedLayouts],
  );

  const handleDragStart: EventCallback = useCallback(
    (_layout, oldItem) => {
      setActivePinId(String(oldItem?.i ?? ""));
    },
    [],
  );

  const handleDragStop: EventCallback = useCallback(
    (layout) => {
      setActivePinId(null);
      const bpLayout = layout as unknown as LayoutItem[];
      updateOptimisticLayouts(bpLayout);
      persistLayout(bpLayout);
    },
    [persistLayout, updateOptimisticLayouts],
  );

  const handleResizeStart: EventCallback = useCallback(
    (_layout, oldItem) => {
      setActivePinId(String(oldItem?.i ?? ""));
    },
    [],
  );

  const handleResizeStop: EventCallback = useCallback(
    (layout) => {
      setActivePinId(null);
      const bpLayout = layout as unknown as LayoutItem[];
      updateOptimisticLayouts(bpLayout);
      persistLayout(bpLayout);
    },
    [persistLayout, updateOptimisticLayouts],
  );

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-8 text-small text-ink-tertiary">
        <IconLoader2 size={16} className="animate-spin" />
        Loading pins…
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="-mx-5 w-[calc(100%+2.5rem)] space-y-3"
    >
      <div className="flex items-center justify-between px-5">
        <div>
          <h2 className="text-h3 text-ink-primary">Pinned workspace</h2>
          <p className="mt-0.5 text-small text-ink-tertiary">
            Business insights, project insights, dashboard widgets, and charts you selected.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
          className="inline-flex items-center gap-1 rounded-md border border-line-tertiary px-2.5 py-1 text-small font-medium text-ink-secondary transition-colors hover:border-line-secondary hover:bg-bg-tertiary disabled:opacity-50"
        >
          <IconRefresh size={14} className={refreshMutation.isPending ? "animate-spin" : ""} />
          Refresh live widgets
        </button>
      </div>
      {layoutError && (
        <p className="px-5 text-small text-red-600">{layoutError}</p>
      )}
      {pins.length === 0 && (
        <div className="mx-5 rounded-xl border border-dashed border-line-secondary bg-bg-primary px-5 py-10 text-center">
          <p className="text-[13px] font-medium text-ink-primary">Your pinned workspace is ready.</p>
          <p className="mt-1 text-small text-ink-tertiary">
            Pin an insight, dashboard widget, or a new chart suggestion to build this area.
          </p>
        </div>
      )}
      <div className="w-full">
        {mounted && pins.length > 0 && (
          <ResponsiveGridLayout
            className="layout"
            breakpoints={GRID_BREAKPOINTS}
            cols={GRID_COLS}
            rowHeight={GRID_ROW_HEIGHT}
            margin={GRID_MARGIN}
            containerPadding={[20, 10]}
            layouts={measuredLayouts ?? displayLayouts}
            onLayoutChange={handleLayoutChange}
            onDragStart={handleDragStart}
            onDragStop={handleDragStop}
            onResizeStart={handleResizeStart}
            onResizeStop={handleResizeStop}
            onBreakpointChange={(bp) =>
              setCurrentBreakpoint(bp as keyof typeof GRID_BREAKPOINTS)
            }
            dragConfig={GRID_DRAG_CONFIG}
            resizeConfig={GRID_RESIZE_CONFIG}
            width={containerWidth}
          >
            {pins.map((pin) => {
              const insightId = getPinInsightId(pin);
              return (
                <div key={pin.id} className="h-full w-full">
                  <PinCard
                    pin={pin}
                    feedback={feedbackById[insightId]}
                    savingFeedback={savingFeedback}
                    onUnpin={(p) => deleteMutation.mutate(p)}
                    onRefresh={() => refreshMutation.mutate()}
                    onFeedbackSave={handleFeedbackSave}
                    onFeedbackRemove={handleFeedbackRemove}
                    onFeedbackRespond={handleFeedbackRespond}
                    onCreateAction={handleCreateAction}
                    governance={governanceById[insightId]}
                    onHeightChange={handleHeightChange}
                    isResizing={activePinId === String(pin.id)}
                  />
                </div>
              );
            })}
          </ResponsiveGridLayout>
        )}
      </div>

      <CreateActionFromInsightDialog
        open={createActionOpen}
        onClose={() => setCreateActionOpen(false)}
        insight={selectedInsight}
      />
    </div>
  );
}
