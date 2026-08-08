"use client";


import { useCallback, useState } from "react";
import {
  IconChartHistogram,
  IconLayoutDashboard,
  IconBulb,
  IconCheck,
  IconLoader2,
  IconDeviceFloppy,
  IconPlayerPlay,
  IconSparkles,
  IconArrowUp,
} from "@tabler/icons-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/api-client";
import { AutosizeTextarea } from "@/components/ui/autosize-textarea";
import {
  suggestQueries,
  suggestDashboards,
  suggestInsights,
  saveDashboardSuggestion,
  type QuerySuggestionsProject,
  type DashboardSuggestionsProject,
  type ProjectResult,
  type InsightCard,
} from "@/lib/api/home-intelligence";
import type {
  GovernanceItem,
  InsightFeedbackRecord,
} from "@/lib/api/insight-feedback";
import {
  IntelligenceCard,
  InsightChartBlock,
} from "@/components/tablescope/home/intelligence-card";
import { QuerySuggestionPreviewModal } from "@/components/tablescope/home/query-suggestion-preview-modal";
import { getDefaultOptions } from "@/lib/visualizations/chartRegistry";


export function ProjectHeader({
  name,
  color,
}: {
  name: string;
  color: string;
}) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ backgroundColor: color }}
      />
      <h3 className="text-h3 text-ink-primary">{name}</h3>
    </div>
  );
}