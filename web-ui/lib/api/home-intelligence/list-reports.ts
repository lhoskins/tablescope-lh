"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { ReportRecord } from "./report-record";



export function listReports(): Promise<ReportRecord[]> {
  return apiClient.get("/api/reports");
}