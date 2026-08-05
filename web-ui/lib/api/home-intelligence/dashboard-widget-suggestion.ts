"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { InsightChart } from "./insight-chart";



export interface DashboardWidgetSuggestion {
  title: string;
  subtitle?: string;
  /** Plain-English, data-grounded explanation of what the chart shows. */
  explanation?: string;
  /** Value format for the metric: percent | currency | count | number. */
  format?: string;
  chartType: string;
  chart: InsightChart;
  sql: string;
  labelColumn: string;
  valueColumn: string;
}