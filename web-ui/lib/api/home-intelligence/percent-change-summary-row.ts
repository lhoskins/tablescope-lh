"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { PercentChangeSummaryCell } from "./percent-change-summary-cell";
import { PercentChangeSummaryStatistics } from "./percent-change-summary-statistics";



export interface PercentChangeSummaryRow {
  insight_id: string;
  title: string;
  project_id: number;
  project_name: string;
  project_color: string | null;
  priority_score: number | null;
  source_grain: string | null;
  supported_intervals: string[];
  data_through: string | null;
  cells: Record<string, PercentChangeSummaryCell>;
  statistics: PercentChangeSummaryStatistics;
}