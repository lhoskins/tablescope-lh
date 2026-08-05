"use client";


import { Fragment, type ReactNode, useMemo, useState } from "react";
import {
  IconChevronRight,
  IconPin,
  IconPinnedFilled,
} from "@tabler/icons-react";

import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { canManageProjectActions } from "@/lib/auth";
import { InsightAnalysisStrip } from "../insight-analysis-strip";
import { InsightTimeSeriesChart } from "../../insights/insight-time-series-chart";
import { WidgetRenderer } from "@/components/dashboard/WidgetRenderer";
import type {
  VisualizationOptions,
  WidgetConfig,
  WidgetType,
} from "@/components/dashboard/types";
import type {
  InsightCallout,
  InsightCard as InsightCardData,
  InsightChart,
  TimeSeriesViewState,
  VizCandidate,
} from "@/lib/api/home-intelligence";
import type { GovernanceItem, InsightFeedbackRecord, InsightSentiment } from "@/lib/api/insight-feedback";
import { ChartSuggestionDialog } from "../chart-suggestion-dialog";
import { InsightExplanationPanel } from "../insight-explanation-panel";
import { InsightFeedbackDialog } from "../insight-feedback-dialog";
import {
  InsightFeedbackStatusBadge,
  InsightFeedbackStatusDialog,
  InsightGovernanceBadge,
} from "../insight-feedback-status";
import { InsightCardActionToolbar } from "@/components/tablescope/insights/insight-card-action-toolbar";
import { exportInsightCardPng, insightPngFilename } from "@/lib/insights/export-png";
import {
  canExportInsightCsv,
  exportInsightCardCsv,
  insightCsvFilename,
} from "@/lib/insights/export-csv";
import { useToasts, ToastViewport } from "@/components/ui/toast";
import { CARD_SEVERITY } from "@/lib/ui/insight-tones";import { stripStars } from "./strip-stars";



/** Render a string with `**bold**` markers as bold spans; strip stray `**`. */
export function renderBold(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-ink-primary">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <Fragment key={i}>{stripStars(part)}</Fragment>;
  });
}