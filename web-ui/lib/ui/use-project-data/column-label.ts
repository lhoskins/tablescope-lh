"use client";


import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { apiClient } from "@/lib/api-client";
import { useCurrentUser, useProjectSummaries } from "../use-shell-data";
import type {
  PresentationDescriptor,
  ResponseEnvelope,
} from "@/lib/api/ai-actions";
import type {
  CurrentUser,
  ProjectSummary,
  TenantSummary,
} from "../types";


export function columnLabel(col: unknown): { name: string; type: string } {
  if (col && typeof col === "object") {
    const rec = col as Record<string, unknown>;
    const name =
      typeof rec.name === "string"
        ? rec.name
        : typeof rec.column === "string"
          ? rec.column
          : "";
    const type =
      typeof rec.type === "string"
        ? rec.type
        : typeof rec.dataType === "string"
          ? rec.dataType
          : "";
    if (name) return { name, type };
  }
  if (Array.isArray(col)) {
    return { name: String(col[0] ?? ""), type: String(col[1] ?? "") };
  }
  return { name: String(col ?? ""), type: "" };
}