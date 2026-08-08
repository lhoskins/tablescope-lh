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
  IconPinnedOff,
  IconRefresh,
  IconGripVertical,
} from "@tabler/icons-react";
import type { WidgetConfig } from "@/components/dashboard/types";
import { WidgetRenderer } from "@/components/dashboard/WidgetRenderer";
import { IntelligenceCard } from "../intelligence-card";
import {
  getHomePins,
  deleteHomePin,
  updateHomePinLayout,
  refreshAllHomePins,
  type HomePin,
} from "@/lib/api/home-pins";
import type { InsightCard } from "@/lib/api/home-intelligence";
import type { GovernanceItem, InsightFeedbackRecord } from "@/lib/api/insight-feedback";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";
import {
  CreateActionFromInsightDialog,
  type ActionableInsight,
} from "@/components/tablescope/project-actions/create-action-from-insight-dialog";import { HomePinItem } from "./home-pin-item";



export function PinContent({
  pin,
  feedback,
  savingFeedback,
  onUnpin,
  onFeedbackSave,
  onFeedbackRemove,
  onFeedbackRespond,
  onCreateAction,
  governance,
}: {
  pin: HomePinItem;
  feedback?: InsightFeedbackRecord | null;
  savingFeedback?: boolean;
  onUnpin?: (pin: HomePinItem) => void;
  onFeedbackSave?: (pin: HomePinItem, payload: {
    sentiment: "agree" | "disagree";
    reason_codes: string[];
    comment: string;
  }) => void;
  onFeedbackRemove?: (pin: HomePinItem) => void;
  onFeedbackRespond?: (pin: HomePinItem, response: string) => void;
  onCreateAction?: (pin: HomePinItem) => void;
  governance?: GovernanceItem | null;
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
        pinned
        frozen
        onUnpin={onUnpin ? () => onUnpin(pin) : undefined}
        feedback={feedback}
        savingFeedback={savingFeedback}
        onFeedbackSave={
          onFeedbackSave ? (payload) => onFeedbackSave(pin, payload) : undefined
        }
        onFeedbackRemove={
          onFeedbackRemove ? () => onFeedbackRemove(pin) : undefined
        }
        onFeedbackRespond={
          onFeedbackRespond ? (response) => onFeedbackRespond(pin, response) : undefined
        }
        onCreateAction={
          onCreateAction ? () => onCreateAction(pin) : undefined
        }
        governance={governance}
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