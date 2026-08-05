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
import { PinContent } from "./pin-content";



export function PinCard({
  pin,
  feedback,
  savingFeedback,
  onUnpin,
  onRefresh,
  onFeedbackSave,
  onFeedbackRemove,
  onFeedbackRespond,
  onCreateAction,
  governance,
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
  onFeedbackRespond?: (pin: HomePinItem, response: string) => void;
  onCreateAction?: (pin: HomePinItem) => void;
  governance?: GovernanceItem | null;
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
      {!isInsight && (
        <button
          type="button"
          onClick={() => onUnpin(pin)}
          title="Unpin"
          className="rounded p-1 text-ink-tertiary hover:bg-bg-tertiary hover:text-danger"
        >
          <IconPinnedOff size={14} />
        </button>
      )}
    </div>
  );

  if (isInsight) {
    return (
      <div className="flex h-full flex-col rounded-xl border border-line-tertiary bg-white">
        <div className="widget-drag-handle flex items-center justify-between rounded-t-xl border-b border-line-tertiary bg-bg-secondary/50 px-3 py-2">
          <IconGripVertical size={14} className="shrink-0 text-ink-tertiary" />
          {actions}
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <PinContent
            pin={pin}
            feedback={feedback}
            savingFeedback={savingFeedback}
            onUnpin={onUnpin}
            onFeedbackSave={onFeedbackSave}
            onFeedbackRemove={onFeedbackRemove}
            onFeedbackRespond={onFeedbackRespond}
            onCreateAction={onCreateAction}
            governance={governance}
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
    <div className="flex h-full flex-col rounded-xl border border-line-tertiary bg-white shadow-sm">
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
          onUnpin={onUnpin}
          onFeedbackSave={onFeedbackSave}
          onFeedbackRemove={onFeedbackRemove}
          onFeedbackRespond={onFeedbackRespond}
          onCreateAction={onCreateAction}
          governance={governance}
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