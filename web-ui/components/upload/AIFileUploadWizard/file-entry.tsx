"use client";


import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";import { TagChip } from "./tag-chip";
import { KPIChip } from "./kpichip";
import { AnalysisResult } from "./analysis-result";



export type FileEntry = {
  id: string;
  fileName: string;
  status: "analyzing" | "ready" | "creating" | "done" | "error";
  analysis: AnalysisResult | null;
  tags: TagChip[];
  kpis: KPIChip[];
  displayName: string;
  userNotes: string;
  error?: string;
  result?: Record<string, unknown>;
  newTag: string;
};