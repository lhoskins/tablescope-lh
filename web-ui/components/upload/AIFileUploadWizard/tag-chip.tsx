"use client";


import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";


// ── Types ────────────────────────────────────────────────────────────────

export type TagChip = {
  tag_key: string;
  display_name: string;
  tag?: string;
  tag_type?: string;
  source?: "ai" | "catalog" | "user" | "system";
  confidence?: number;
  accepted?: boolean;
  reason?: string;
};