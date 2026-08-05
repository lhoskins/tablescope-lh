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
import { CARD_SEVERITY } from "@/lib/ui/insight-tones";import { buildMultiDimWidget } from "./build-multi-dim-widget";



export function InsightChartView({
  chart,
  height: heightProp,
  options,
}: {
  chart: InsightChart;
  height?: number;
  /**
   * Extra renderer options merged over the defaults — used to carry annotations
   * an analysis produced (e.g. the exact points a method flagged) through to
   * the chart.
   */
  options?: Partial<VisualizationOptions>;
}) {
  const dataRows = chart.data.rows;
  const series = chart.data.series;

  if (dataRows && dataRows.length > 0) {
    const widget = buildMultiDimWidget(chart, dataRows);
    if (options) {
      widget.visualizationOptions = { ...widget.visualizationOptions, ...options };
    }
    const height =
      heightProp ??
      (chart.type === "funnel" || chart.type === "sankey"
        ? 260
        : chart.type === "heatmap"
          ? 240
          : 220);
    return (
      <div className="w-full" style={{ height }}>
        <WidgetRenderer widget={widget} data={dataRows} />
      </div>
    );
  }

  if (!series || series.length === 0) return null;

  // Two-metric charts (combo/scatter/bubble) carry a second value; expose both
  // columns so the renderer can map them onto the right axes.
  const hasValue2 = series.some((s) => typeof s.value2 === "number");
  const labels = chart.seriesLabels;
  const roles = chart.roles;
  const valueName = labels?.value ?? roles?.y ?? "value";
  const value2Name = labels?.value2 ?? roles?.y2 ?? "value2";
  const xName = roles?.x ?? "label";

  // For scatter, the first metric is the X axis and the second is the Y axis.
  const isScatter = chart.type === "scatter";
  const xColumnName = isScatter ? valueName : xName;
  const yColumnName = isScatter ? value2Name : valueName;

  const rows = series.map((s) => {
    if (isScatter) {
      return { [valueName]: s.value, [value2Name]: s.value2 ?? 0 };
    }
    if (hasValue2) {
      return { [xName]: s.label, [valueName]: s.value, [value2Name]: s.value2 ?? 0 };
    }
    return { [xName]: s.label, [valueName]: s.value };
  });

  const base: WidgetConfig = {
    id: "insight-chart",
    type: chart.type as WidgetType,
    chartSubtype: (chart.subtype || undefined) as WidgetConfig["chartSubtype"],
    title: "",
    dataSource: { kind: "custom_sql" },
    xColumn: xColumnName,
    xColumnType: isScatter ? "number" : "string",
    yColumn: yColumnName,
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    visualizationOptions: { showLegend: false, showGrid: false, ...options },
    colSpan: 1,
    position: 0,
  };

  let widget: WidgetConfig = base;
  if ((chart.type === "combo" && hasValue2) || chart.type === "scatter") {
    widget = { ...base, y2Column: isScatter ? undefined : value2Name, y2Aggregation: "sum" };
  }

  // Horizontal bars stack their category labels down the y-axis, so give each
  // bar vertical room instead of cramming them into a fixed 180px box.
  const isHorizontalBar =
    chart.type === "bar" &&
    (chart.subtype === "horizontal_bar" ||
      chart.subtype === "stacked_horizontal");
  const height =
    heightProp ??
    (isHorizontalBar
      ? Math.min(520, Math.max(180, rows.length * 28 + 48))
      : 180);

  return (
    <div className="w-full" style={{ height }}>
      <WidgetRenderer widget={widget} data={rows} />
    </div>
  );
}