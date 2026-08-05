"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { SaveCardToDashboardPayload } from "./save-card-to-dashboard-payload";
import { SaveCardToDashboardResponse } from "./save-card-to-dashboard-response";



export function saveCardToDashboard(
  body: SaveCardToDashboardPayload,
): Promise<SaveCardToDashboardResponse> {
  return apiClient.post("/api/ai/home/save-card-to-dashboard", body);
}