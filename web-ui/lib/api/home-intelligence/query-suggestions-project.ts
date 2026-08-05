"use client";


import { apiClient } from "@/lib/api-client";
import type {
  MethodEnvelope,
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";import { QuerySuggestion } from "./query-suggestion";



export interface QuerySuggestionsProject {
  projectId: string;
  projectName: string;
  projectColor: string;
  suggestions: QuerySuggestion[];
}