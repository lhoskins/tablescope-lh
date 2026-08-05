"use client";


import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useNotifyScopesChanged } from "@/lib/ui/scope-refresh";
import {
  IconArrowNarrowRight,
  IconArrowsExchange,
  IconChevronDown,
  IconDeviceFloppy,
  IconGripVertical,
  IconMaximize,
  IconPencil,
  IconPlus,
  IconSearch,
  IconSparkles,
  IconTrash,
  IconX,
  IconZoomIn,
  IconZoomOut,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import {
  scopesApi,
  type MatchMode,
  type ScopeAISuggestion,
  type ScopeBuilderTable,
  type ScopeDirection,
  type ScopeMap,
} from "@/lib/api/scopes";


export function confidenceLabel(c: number | null): {
  text: string;
  tone: "success" | "warning" | "neutral";
} {
  if (c == null) return { text: "Medium", tone: "warning" };
  if (c >= 0.8) return { text: "High", tone: "success" };
  if (c >= 0.5) return { text: "Medium", tone: "warning" };
  return { text: "Low", tone: "neutral" };
}