"use client";


import { useState, useCallback, useEffect, useRef, lazy, Suspense } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { UnifiedUploadDialog } from "@/components/uploads/unified-upload-dialog";


// ── Types ──────────────────────────────────────────────────────────

export type ProjectDocument = {
  id: number;
  title: string | null;
  filename: string;
  original_filename: string;
  asset_type: string;
  content_type: string | null;
  file_extension: string | null;
  file_size_bytes: number | null;
  status: string;
  ai_status: string | null;
  ai_summary: string | null;
  ai_metadata: Record<string, unknown> | null;
  visibility: string;
  created_at: string;
};