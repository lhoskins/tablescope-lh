"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { ReportSection } from "./report-section";
import { ReportRecord } from "./report-record";



export function createReport(body: {
  title: string;
  sections: ReportSection[];
  share_settings?: Record<string, unknown>;
}): Promise<ReportRecord> {
  return apiClient.post("/api/reports", body);
}