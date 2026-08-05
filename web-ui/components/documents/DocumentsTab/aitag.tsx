"use client";


import { useState, useCallback, useEffect, useRef, lazy, Suspense } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { UnifiedUploadDialog } from "@/components/uploads/unified-upload-dialog";


export type AITag = {
  tag_key: string;
  display_name: string;
  confidence: number;
  source: string;
};