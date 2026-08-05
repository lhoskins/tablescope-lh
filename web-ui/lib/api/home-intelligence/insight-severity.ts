"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { InsightCard } from "./insight-card";



// ── Insight card shape (mirrors the platform-api InsightCard dict) ───────────

export type InsightSeverity =
  | "critical"
  | "urgent"
  | "warning"
  | "watch"
  | "trend"
  | "opportunity"
  | "recommendation"
  | "informational"
  | "info";