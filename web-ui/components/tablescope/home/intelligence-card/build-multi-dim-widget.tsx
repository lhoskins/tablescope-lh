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
import { CARD_SEVERITY } from "@/lib/ui/insight-tones";
import { autoValueScale } from "@/components/dashboard/EChartsWidget/format-number";


/**
 * Render a chart through the same `WidgetRenderer` the dashboard uses, so
 * Intelligence cards share the dashboard's full chart catalog and styling.
 * The backend emits a `{label, value}` series plus a dashboard chart
 * `type`/`subtype`; we adapt that into a minimal `WidgetConfig` + rows.
 */
export function buildMultiDimWidget(chart: InsightChart, dataRows: Record<string, unknown>[]): WidgetConfig {
  const roles = chart.roles ?? {};
  const type = chart.type as WidgetType;
  const base: WidgetConfig = {
    id: "insight-chart",
    type,
    chartSubtype: (chart.subtype || undefined) as WidgetConfig["chartSubtype"],
    title: "",
    dataSource: { kind: "custom_sql" },
    xColumn: roles.x ?? "",
    yColumn: roles.value ?? roles.y ?? "",
    aggregation: "sum",
    sortBy: "x_asc",
    filters: [],
    visualizationOptions: { showLegend: type === "radar", showGrid: false },
    colSpan: 1,
    position: 0,
  };

  let widget: WidgetConfig;
  if (type === "scatter" || type === "effect_scatter") {
    widget = {
      ...base,
      xColumn: roles.x ?? "x",
      yColumn: roles.y ?? "y",
      groupByColumn: roles.group,
      xColumnType: "number",
    };
  } else if (type === "radar") {
    widget = { ...base, xColumn: roles.x ?? "subject", yColumn: roles.value ?? "value", groupByColumn: roles.group ?? "metric" };
  } else if (type === "heatmap") {
    widget = { ...base, xColumn: roles.x ?? "", yColumn: roles.value ?? "", groupByColumn: roles.y ?? roles.group ?? "" };
  } else if (type === "treemap" || type === "sankey" || type === "sunburst" || type === "tree" || type === "graph") {
    widget = { ...base, xColumn: roles.x ?? "", yColumn: roles.value ?? "", groupByColumn: roles.group ?? "" };
  } else if (type === "funnel" || type === "gauge") {
    widget = { ...base, xColumn: roles.x ?? (Object.keys(dataRows[0] ?? {})[0] || ""), yColumn: roles.value ?? "" };
  } else if (type === "parallel" || type === "lines" || type === "candlestick" || type === "boxplot" || type === "pictorial_bar" || type === "theme_river" || type === "map") {
    widget = { ...base, xColumn: roles.x ?? "", yColumn: roles.value ?? roles.y ?? "", groupByColumn: roles.group ?? "" };
  } else if (type === "combo" && roles.y2) {
    widget = { ...base, xColumn: roles.x ?? "label", yColumn: roles.y ?? "value", y2Column: roles.y2, y2Aggregation: "sum" };
  } else {
    widget = { ...base, xColumn: roles.x ?? "label", yColumn: roles.value ?? roles.y ?? "value" };
  }

  // A shared K/M axis unit, picked from this chart's own value range (see
  // autoValueScale) -- e.g. a revenue-by-customer bar chart in the tens of
  // millions reads "34.8M" on every tick/bar-end label instead of
  // "34,840,581.67". Harmless for chart types with no numeric value axis
  // (pie, heatmap, ...); their renderers simply never read valueScale.
  const valueColumns = [widget.yColumn, widget.y2Column].filter((c): c is string => !!c);
  const values = dataRows.flatMap((row) =>
    valueColumns.map((col) => {
      const v = row[col];
      return typeof v === "number" ? v : Number(v);
    }),
  );
  const valueScale = autoValueScale(values);
  if (valueScale) {
    widget.visualizationOptions = { ...widget.visualizationOptions, valueScale };
  }

  return widget;
}