"use client";


import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";import { TagChip } from "./tag-chip";
import { KPIChip } from "./kpichip";



export type AnalysisResult = {
  upload_session_id: string;
  file: {
    file_name: string;
    file_type: string;
    file_size_bytes: number;
    row_count: number;
    column_count: number;
    sheet_name?: string;
  };
  summary: {
    ai_summary: string;
    ai_usage_summary: string;
    ai_quality_summary: string;
    business_domain?: string;
    process_area?: string;
  };
  fields: Array<{
    field_name: string;
    detected_type: string;
    null_count: number;
    null_percent: number;
    distinct_count: number;
    sample_values: string[];
    ai_description?: string;
  }>;
  tags: TagChip[];
  kpis?: KPIChip[];
  relationship_hints?: Array<{
    source_field: string;
    possible_target: string;
    confidence: number;
  }>;
  data_quality_notes?: string[];
  recommendations: Array<Record<string, unknown>>;
  status: string;
};