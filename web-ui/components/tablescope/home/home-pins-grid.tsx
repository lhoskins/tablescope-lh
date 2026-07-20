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
  GRID_CONTAINER_PADDING,
  GRID_DRAG_CONFIG,
  GRID_MARGIN,
  GRID_RESIZE_CONFIG,
  GRID_ROW_HEIGHT,
  buildResponsiveHomeLayouts,
} from "@/lib/ui/grid-layout";
import {
  IconLoader2,
  IconPinnedOff,
  IconRefresh,
  IconGripVertical,
} from "@tabler/icons-react";
import type { WidgetConfig } from "@/components/dashboard/types";
import { WidgetRenderer } from "@/components/dashboard/WidgetRenderer";
import { IntelligenceCard } from "./intelligence-card";
import {
  getHomePins,
  deleteHomePin,
  updateHomePinLayout,
  refreshAllHomePins,
  type HomePin,
} from "@/lib/api/home-pins";
import type { InsightCard } from "@/lib/api/home-intelligence";
import type { InsightFeedbackRecord } from "@/lib/api/insight-feedback";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";

type HomePinItem = HomePin;

function getPinInsightId(pin: HomePinItem): string {
  const frozen = (pin.frozen_payload ?? pin.config ?? {}) as {
    insightId?: string;
    id?: string;
  };
  return frozen.insightId || frozen.id || pin.pin_key;
}

function PinCard({
  pin,
  feedback,
  savingFeedback,
  onUnpin,
  onRefresh,
  onFeedbackSave,
  onFeedbackRemove,
}: {
  pin: HomePinItem;
  feedback?: InsightFeedbackRecord | null;
  savingFeedback?: boolean;
  onUnpin: (pin: HomePinItem) => void;
  onRefresh: (pin: HomePinItem) => void;
  onFeedbackSave?: (pin: HomePinItem, payload: {
    sentiment: "agree" | "disagree";
    reason_codes: string[];
    comment: string;
  }) => void;
  onFeedbackRemove?: (pin: HomePinItem) => void;
}) {
  const isLive = pin.pin_type === "live_widget";
  const isInsight = pin.pin_type === "insight_card";

  const actions = (
    <div className="flex items-center gap-1">
      {isLive && (
        <button
          type="button"
          onClick={() => onRefresh(pin)}
          title="Refresh"
          className="rounded p-1 text-ink-tertiary hover:bg-bg-tertiary hover:text-ink-primary"
        >
          <IconRefresh size={14} />
        </button>
      )}
      <button
        type="button"
        onClick={() => onUnpin(pin)}
        title="Unpin"
        className="rounded p-1 text-ink-tertiary hover:bg-bg-tertiary hover:text-danger"
      >
        <IconPinnedOff size={14} />
      </button>
    </div>
  );

  if (isInsight) {
    return (
      <div className="flex h-full flex-col">
        <div className="widget-drag-handle flex items-center justify-between rounded-t-xl border-x border-t border-line-tertiary bg-bg-secondary/50 px-3 py-2">
          <IconGripVertical size={14} className="shrink-0 text-ink-tertiary" />
          {actions}
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <PinContent
            pin={pin}
            feedback={feedback}
            savingFeedback={savingFeedback}
            onFeedbackSave={onFeedbackSave}
            onFeedbackRemove={onFeedbackRemove}
          />
        </div>
        {pin.refresh_error && (
          <div className="px-3 py-1.5 text-[11px] text-red-600">
            {pin.refresh_error}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col rounded-xl border border-line-tertiary bg-bg-primary shadow-sm">
      <div className="widget-drag-handle flex items-center justify-between border-b border-line-tertiary bg-bg-secondary/50 px-3 py-2">
        <div className="flex items-center gap-2 overflow-hidden">
          <IconGripVertical size={14} className="shrink-0 text-ink-tertiary" />
          <span className="truncate text-[13px] font-medium text-ink-primary">
            {pin.title || "Untitled"}
          </span>
        </div>
        {actions}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <PinContent
          pin={pin}
          feedback={feedback}
          savingFeedback={savingFeedback}
          onFeedbackSave={onFeedbackSave}
          onFeedbackRemove={onFeedbackRemove}
        />
      </div>
      {pin.refresh_error && (
        <div className="px-3 py-1.5 text-[11px] text-red-600">
          {pin.refresh_error}
        </div>
      )}
    </div>
  );
}

function PinContent({
  pin,
  feedback,
  savingFeedback,
  onFeedbackSave,
  onFeedbackRemove,
}: {
  pin: HomePinItem;
  feedback?: InsightFeedbackRecord | null;
  savingFeedback?: boolean;
  onFeedbackSave?: (pin: HomePinItem, payload: {
    sentiment: "agree" | "disagree";
    reason_codes: string[];
    comment: string;
  }) => void;
  onFeedbackRemove?: (pin: HomePinItem) => void;
}) {
  if (pin.pin_type === "insight_card") {
    const card = (pin.frozen_payload ?? pin.config ?? {}) as unknown as InsightCard;
    if (!card.title) {
      return (
        <div className="text-small text-ink-tertiary">Insight snapshot unavailable</div>
      );
    }
    return (
      <IntelligenceCard
        card={card}
        hideActions
        frozen
        feedback={feedback}
        savingFeedback={savingFeedback}
        onFeedbackSave={
          onFeedbackSave ? (payload) => onFeedbackSave(pin, payload) : undefined
        }
        onFeedbackRemove={
          onFeedbackRemove ? () => onFeedbackRemove(pin) : undefined
        }
      />
    );
  }

  const widget = (pin.config?.widget ?? {}) as unknown as WidgetConfig;
  const cachedData = (pin.config?.cachedData ?? {}) as { columns?: string[]; rows?: Record<string, unknown>[] };
  if (!widget.type) {
    return (
      <div className="text-small text-ink-tertiary">Widget config unavailable</div>
    );
  }
  return (
    <div className="h-full">
      <WidgetRenderer widget={widget} data={cachedData.rows ?? []} />
    </div>
  );
}

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
    saveFeedback,
    removeFeedback,
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

  const { width: containerWidth, containerRef, mounted } = useContainerWidth({
    initialWidth: 1280,
  });

  const [currentBreakpoint, setCurrentBreakpoint] = useState<
    keyof typeof GRID_BREAKPOINTS
  >("lg");
  const [localLayouts, setLocalLayouts] = useState<ResponsiveLayouts | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);

  const handleFeedbackRemove = (pin: HomePinItem) => {
    const card = (pin.frozen_payload ?? pin.config ?? {}) as unknown as InsightCard;
    const insightId = card.insightId || card.id;
    const projectId = pin.project_id ?? Number(card.projectId);
    if (!insightId || !projectId) return;
    void removeFeedback({ insightId, projectId });
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
    (_layout: Layout, allLayouts: ResponsiveLayouts) => {
      setLocalLayouts(allLayouts);
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

  const handleDragStop: EventCallback = useCallback(
    (layout) => {
      persistLayout(layout as unknown as LayoutItem[]);
    },
    [persistLayout],
  );

  const handleResizeStop: EventCallback = useCallback(
    (layout) => {
      persistLayout(layout as unknown as LayoutItem[]);
    },
    [persistLayout],
  );

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-8 text-small text-ink-tertiary">
        <IconLoader2 size={16} className="animate-spin" />
        Loading pins…
      </div>
    );
  }

  if (pins.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-h3 text-ink-primary">Pinned to Home</h2>
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
        <p className="text-small text-red-600">{layoutError}</p>
      )}
      <div ref={containerRef} className="w-full">
        {mounted && (
          <ResponsiveGridLayout
            className="layout"
            layouts={displayLayouts}
            breakpoints={GRID_BREAKPOINTS}
            cols={GRID_COLS}
            rowHeight={GRID_ROW_HEIGHT}
            margin={GRID_MARGIN}
            containerPadding={GRID_CONTAINER_PADDING}
            onLayoutChange={handleLayoutChange}
            onDragStop={handleDragStop}
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
                  />
                </div>
              );
            })}
          </ResponsiveGridLayout>
        )}
      </div>
    </div>
  );
}
