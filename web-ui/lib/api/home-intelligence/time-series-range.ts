"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";

export type TimeSeriesRange = "7d" | "30d" | "90d" | "1y" | "2y";