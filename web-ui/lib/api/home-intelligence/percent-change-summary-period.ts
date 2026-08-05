"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface PercentChangeSummaryPeriod {
  key: string;
  label: string;
  start: string;
  end: string;
  is_latest: boolean;
}