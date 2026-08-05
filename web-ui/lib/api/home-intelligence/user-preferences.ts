"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { IntelligenceSettings } from "./intelligence-settings";



export interface UserPreferences {
  intelligence: IntelligenceSettings;
}