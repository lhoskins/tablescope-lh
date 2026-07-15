"use client";

import { useMemo } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  batchGetInsightFeedback,
  deleteInsightFeedback,
  upsertInsightFeedback,
  type InsightFeedbackRecord,
  type InsightSentiment,
} from "@/lib/api/insight-feedback";

export interface SaveInsightFeedbackArgs {
  insightId: string;
  projectId: number;
  insightType?: string;
  sentiment: InsightSentiment;
  reason_codes: string[];
  comment: string;
  cardSnapshot?: Record<string, unknown>;
  explanationSnapshot?: Record<string, unknown>;
  modelMetadata?: Record<string, unknown>;
}

export interface RemoveInsightFeedbackArgs {
  insightId: string;
  projectId: number;
}

function feedbackQueryKey(insightIds: string[]) {
  return ["insight-feedback", insightIds];
}

export function useInsightFeedback(insightIds: string[]) {
  const queryClient = useQueryClient();
  const ids = useMemo(
    () => Array.from(new Set(insightIds.filter(Boolean))),
    [insightIds],
  );

  const { data: feedbackById = {}, isLoading } = useQuery<
    Record<string, InsightFeedbackRecord>
  >({
    queryKey: feedbackQueryKey(ids),
    queryFn: async () => {
      if (ids.length === 0) return {};
      const res = await batchGetInsightFeedback({ insight_ids: ids });
      const map: Record<string, InsightFeedbackRecord> = {};
      for (const item of res.items) {
        map[item.insight_id] = item;
      }
      return map;
    },
    enabled: ids.length > 0,
  });

  const saveMutation = useMutation({
    mutationFn: async (args: SaveInsightFeedbackArgs) => {
      const fingerprint = `${args.insightId}:${args.projectId}`;
      return upsertInsightFeedback(args.insightId, {
        project_id: args.projectId,
        sentiment: args.sentiment,
        reason_codes: args.reason_codes,
        comment: args.comment,
        insight_type: args.insightType,
        insight_fingerprint: fingerprint,
        card_snapshot: args.cardSnapshot,
        explanation_snapshot: args.explanationSnapshot,
        model_metadata: args.modelMetadata,
      });
    },
    onSuccess: (data) => {
      queryClient.setQueryData<Record<string, InsightFeedbackRecord>>(
        feedbackQueryKey(ids),
        (prev) => ({ ...(prev ?? {}), [data.insight_id]: data }),
      );
    },
  });

  const removeMutation = useMutation({
    mutationFn: async (args: RemoveInsightFeedbackArgs) => {
      await deleteInsightFeedback(args.insightId, args.projectId);
      return args.insightId;
    },
    onSuccess: (insightId) => {
      queryClient.setQueryData<Record<string, InsightFeedbackRecord>>(
        feedbackQueryKey(ids),
        (prev) => {
          if (!prev) return {};
          const next = { ...prev };
          delete next[insightId];
          return next;
        },
      );
    },
  });

  return {
    feedbackById,
    isLoading,
    saveFeedback: saveMutation.mutateAsync,
    removeFeedback: removeMutation.mutateAsync,
    saving: saveMutation.isPending || removeMutation.isPending,
  };
}
