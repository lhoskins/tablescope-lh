"use client";


import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  clearBusinessInsightCache,
  getHomeIntelligenceRunStatus,
  getIntelligenceSnapshot,
  getPreferences,
  refreshHomeIntelligence,
  streamHomeIntelligence,
  updatePreferences,
  type CrossProjectSynthesis,
  type InsightCard,
  type IntelligenceEvent,
  type IntelligenceSettings,
  type IntelligenceSnapshot,
  type ProjectResult,
  type StreamProject,
} from "@/lib/api/home-intelligence";
import { SaveInsightToDashboardModal } from "../save-insight-to-dashboard-modal";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { formatLastUpdated } from "@/lib/format-datetime";
import { LoadingCard } from "../intelligence-card";
import { useInsightFeedback } from "@/lib/hooks/use-insight-feedback";
import type { InsightCardActionHandlers } from "@/components/tablescope/insights/insight-section";
import type { FilterableProject } from "../intelligence-strip";
import { IntelligenceWorkspace } from "@/components/tablescope/insights/intelligence-workspace";


export type Status = "idle" | "streaming" | "complete" | "error";