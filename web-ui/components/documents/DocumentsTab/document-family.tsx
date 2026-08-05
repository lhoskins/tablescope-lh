"use client";


import { useState, useCallback, useEffect, useRef, lazy, Suspense } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { UnifiedUploadDialog } from "@/components/uploads/unified-upload-dialog";


export type DocumentFamily = {
  family_name: string;
  family_key: string;
  family_type: string;
  confidence: number;
  role: string;
  reason: string;
  auto_link: boolean;
};