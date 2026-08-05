"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { UserPreferences } from "./user-preferences";



export function getPreferences(): Promise<UserPreferences> {
  return apiClient.get("/api/users/preferences");
}