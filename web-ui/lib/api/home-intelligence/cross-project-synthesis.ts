"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";


export interface CrossProjectSynthesis {
  headline: string;
  body: string;
  projectIds: string[];
}