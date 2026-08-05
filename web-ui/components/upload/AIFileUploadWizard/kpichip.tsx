"use client";


import { useState, useCallback } from "react";
import { apiClient } from "@/lib/api-client";


export type KPIChip = {
  kpi_key: string;
  display_name: string;
  source?: "catalog" | "user";
  confidence?: number;
  accepted?: boolean;
  field_mapping?: Record<string, string>;
  reason?: string;
};