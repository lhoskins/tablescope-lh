"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ResponsiveGridLayout, type Layout, type LayoutItem } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
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
  return (
    <div className="flex h-full flex-col rounded-xl border border-line-tertiary bg-bg-primary shadow-sm">
      <div className="widget-drag-handle flex items-center justify-between border-b border-line-tertiary bg-bg-secondary/50 px-3 py-2">
        <div className="flex items-center gap-2 overflow-hidden">
          <IconGripVertical size={14} className="shrink-0 text-ink-tertiary" />
          <span className="truncate text-[13px] font-medium text-ink-primary">
            {pin.title || "Untitled"}
          </span>
        </div>
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

  const handleFeedbackRemove = (pin: HomePinItem) => {
    const card = (pin.frozen_payload ?? pin.config ?? {}) as unknown as InsightCard;
    const insightId = card.insightId || card.id;
    const projectId = pin.project_id ?? Number(card.projectId);
    if (!insightId || !projectId) return;
    void removeFeedback({ insightId, projectId });
  };

  const [optimisticLayout, setOptimisticLayout] = useState<LayoutItem[] | null>(null);

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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["home-pins"] }),
  });

  const layouts = useMemo(() => {
    const lg: LayoutItem[] = pins.map((pin) => {
      const layout = pin.layout || {};
      return {
        i: String(pin.id),
        x: typeof layout.x === "number" ? layout.x : 0,
        y: typeof layout.y === "number" ? layout.y : 0,
        w: typeof layout.w === "number" ? layout.w : 6,
        h: typeof layout.h === "number" ? layout.h : 4,
        minW: 2,
        minH: 2,
      };
    });
    return { lg };
  }, [pins]);

  const handleLayoutChange = useCallback(
    (layout: Layout) => {
      if (!layout.length) return;
      const mutable = [...layout] as LayoutItem[];
      setOptimisticLayout(mutable);
      layoutMutation.mutate(mutable);
    },
    [layoutMutation],
  );

  const displayLayout = useMemo(() => {
    if (optimisticLayout && optimisticLayout.length === pins.length) {
      return { lg: optimisticLayout };
    }
    return layouts;
  }, [optimisticLayout, pins.length, layouts]);

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
      <ResponsiveGridLayout
        className="layout"
        layouts={displayLayout}
        breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
        cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
        rowHeight={80}
        onLayoutChange={handleLayoutChange}
        dragConfig={{ enabled: true, handle: ".widget-drag-handle", bounded: false, threshold: 3 }}
        resizeConfig={{ enabled: true }}
        width={1200}
      >
        {pins.map((pin) => {
          const insightId = getPinInsightId(pin);
          return (
            <div key={pin.id}>
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
    </div>
  );
}
