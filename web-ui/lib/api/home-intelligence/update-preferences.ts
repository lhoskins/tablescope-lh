"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { IntelligenceSettings } from "./intelligence-settings";
import { UserPreferences } from "./user-preferences";



export function updatePreferences(
  intelligence: Partial<IntelligenceSettings>,
): Promise<UserPreferences> {
  return apiClient.patch("/api/users/preferences", { intelligence });
}