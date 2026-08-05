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


export interface HomeAiSuggestionsCardActions {
  onPin?: (card: InsightCard) => void;
  onSaveToDashboard?: (card: InsightCard) => void;
  onCreateAction?: (card: InsightCard) => void;
  onFeedbackSave?: (
    card: InsightCard,
    payload: {
      sentiment: "agree" | "disagree";
      reason_codes: string[];
      comment: string;
    },
  ) => void;
  onFeedbackRemove?: (card: InsightCard) => void;
  onFeedbackRespond?: (card: InsightCard, response: string) => void;
  feedbackById?: Record<string, InsightFeedbackRecord>;
  savingFeedback?: boolean;
  governanceById?: Record<string, GovernanceItem>;
  pinnedByFingerprint?: Map<string, number>;
  actionsDisclosure?: "always-visible" | "collapsible";
}