"use client";


import { useState, useCallback, useEffect, useRef, lazy, Suspense } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { UnifiedUploadDialog } from "@/components/uploads/unified-upload-dialog";


export function statusBadge(status: string | null | undefined) {
  const s = (status ?? "pending").toLowerCase();
  const colors: Record<string, string> = {
    uploaded: "bg-blue-100 text-blue-700",
    extracting: "bg-yellow-100 text-yellow-700",
    chunking: "bg-yellow-100 text-yellow-700",
    profiling: "bg-purple-100 text-purple-700",
    profiled: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    pending: "bg-slate-100 text-slate-500",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${colors[s] ?? colors.pending}`}>
      {s}
    </span>
  );
}