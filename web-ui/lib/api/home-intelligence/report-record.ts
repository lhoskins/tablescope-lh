"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { ReportSection } from "./report-section";



export interface ReportRecord {
  id: number;
  shareToken: string;
  shareUrl: string;
  title: string;
  sections: ReportSection[];
  shareSettings: Record<string, unknown>;
  createdAt: string | null;
  updatedAt: string | null;
}