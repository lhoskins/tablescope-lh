"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { PercentChangeSummaryPeriod } from "./percent-change-summary-period";
import { PercentChangeSummaryRow } from "./percent-change-summary-row";
import { PercentChangeSummaryPageInfo } from "./percent-change-summary-page-info";



export interface PercentChangeSummaryResponse {
  schema_version: number;
  interval: string;
  range: string;
  as_of: string;
  comparison_label: string;
  periods: PercentChangeSummaryPeriod[];
  rows: PercentChangeSummaryRow[];
  interval_support_counts: Record<string, number>;
  page: PercentChangeSummaryPageInfo;
  excluded_by_reason: Record<string, number>;
  warnings: string[];
}