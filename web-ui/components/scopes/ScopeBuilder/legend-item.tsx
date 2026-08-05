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


export function LegendItem({
  label,
  dashed,
  faded,
}: {
  label: string;
  dashed?: boolean;
  faded?: boolean;
}) {
  return (
    <span className="flex items-center gap-1">
      <svg width="20" height="6" className={cn(faded && "opacity-40")}>
        <line
          x1="0"
          y1="3"
          x2="20"
          y2="3"
          stroke={dashed ? "#9ca3af" : "var(--color-brand-500, #2563eb)"}
          strokeWidth="2"
          strokeDasharray={dashed ? "4 3" : undefined}
        />
      </svg>
      {label}
    </span>
  );
}