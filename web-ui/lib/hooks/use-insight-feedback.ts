"use client";

import { useMemo } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  batchGetInsightFeedback,
  batchGetInsightGovernance,
  deleteInsightFeedback,
  respondToInsightFeedbackRequest,
  upsertInsightFeedback,
  type GovernanceItem,
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

export interface RespondToReviewArgs {
  insightId: string;
  response: string;
}

function feedbackQueryKey(insightIds: string[]) {
  return ["insight-feedback", insightIds];
}

function governanceQueryKey(insightIds: string[], projectId?: number) {
  return ["insight-governance", projectId ?? "all", insightIds];
}

export function useInsightFeedback(insightIds: string[], projectId?: number) {
  const queryClient = useQueryClient();
  const ids = useMemo(
    () => Array.from(new Set(insightIds.filter(Boolean))),
    [insightIds],
  );

  const { data: feedbackById = {}, isLoading: isLoadingFeedback } = useQuery<
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

  const { data: governanceById = {}, isLoading: isLoadingGovernance } = useQuery<
    Record<string, GovernanceItem>
  >({
    queryKey: governanceQueryKey(ids, projectId),
    queryFn: async () => {
      if (ids.length === 0) return {};
      const res = await batchGetInsightGovernance({
        insight_ids: ids,
        project_id: projectId,
      });
      const map: Record<string, GovernanceItem> = {};
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
      if (projectId != null) {
        queryClient.invalidateQueries({
          queryKey: governanceQueryKey([], projectId),
        });
      }
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
      if (projectId != null) {
        queryClient.invalidateQueries({
          queryKey: governanceQueryKey([], projectId),
        });
      }
    },
  });

  const respondMutation = useMutation({
    mutationFn: async (args: RespondToReviewArgs) => {
      return respondToInsightFeedbackRequest(args.insightId, {
        response: args.response,
      });
    },
    onSuccess: (data) => {
      queryClient.setQueryData<Record<string, InsightFeedbackRecord>>(
        feedbackQueryKey(ids),
        (prev) => ({ ...(prev ?? {}), [data.insight_id]: data }),
      );
      if (projectId != null) {
        queryClient.invalidateQueries({
          queryKey: governanceQueryKey([], projectId),
        });
      }
    },
  });

  return {
    feedbackById,
    governanceById,
    isLoading: isLoadingFeedback || isLoadingGovernance,
    saveFeedback: saveMutation.mutateAsync,
    removeFeedback: removeMutation.mutateAsync,
    respondToReview: respondMutation.mutateAsync,
    saving: saveMutation.isPending || removeMutation.isPending,
    responding: respondMutation.isPending,
  };
}
