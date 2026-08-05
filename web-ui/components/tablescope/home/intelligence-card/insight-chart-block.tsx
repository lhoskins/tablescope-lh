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
import { CARD_SEVERITY } from "@/lib/ui/insight-tones";import { InsightChartView } from "./insight-chart-view";
import { KpiGridView } from "./kpi-grid-view";



/**
 * Render an {@link InsightChart} (kpi grid or any dashboard chart) standalone.
 * Shared by the Intelligence feed and the Home dashboard-suggestion previews.
 */
export function InsightChartBlock({
  chart,
  options,
}: {
  chart: InsightChart;
  options?: Partial<VisualizationOptions>;
}) {
  return (
    <>
      {chart.title && (
        <div className="mb-1 text-small text-ink-tertiary">{chart.title}</div>
      )}
      {chart.type === "kpi_grid" && chart.data.kpis ? (
        <KpiGridView kpis={chart.data.kpis} />
      ) : (
        <InsightChartView chart={chart} options={options} />
      )}
    </>
  );
}