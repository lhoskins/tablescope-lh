"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { InsightCard } from "./insight-card";



export interface ProjectResult {
  projectId: string;
  projectName: string;
  projectColor: string;
  insights: InsightCard[];
}