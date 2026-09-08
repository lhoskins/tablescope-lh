"use client";

import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AIDashboardDesigner } from "@/components/tablescope/project/ai-dashboard-designer";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { decideArtifactProposal } from "@/lib/api/conversational-analytics";

/**
 * Shared "review & create" flow for a chat-proposed dashboard, used by every
 * chat surface that renders `TurnBubble`/`TurnBubbles`: opens the existing
 * (separately governed) dashboard designer seeded with the chat prompt, and
 * on completion records the resulting dashboard id against the proposing
 * turn via the artifact-decision endpoint. Failing to record that decision
 * is non-fatal -- the dashboard was already created either way -- so it
 * surfaces as a toast rather than blocking the flow.
 */
export function useChatDashboardReview({
  projectId,
  conversationId,
  onSettled,
}: {
  projectId?: string | null;
  conversationId?: number | null;
  /** Called after a successful accept (or a failed one, after the toast) so
   *  the caller can refetch the conversation and show the updated card. */
  onSettled?: () => void;
}): {
  reviewDashboard: (turnId: number, prompt: string) => void;
  reviewerNode: ReactNode;
} {
  const queryClient = useQueryClient();
  const { toasts, push, dismiss } = useToasts();
  const [proposal, setProposal] = useState<{ turnId: number; prompt: string } | null>(null);

  const reviewDashboard = (turnId: number, prompt: string) => {
    setProposal({ turnId, prompt });
  };

  const reviewerNode = projectId ? (
    <>
      <AIDashboardDesigner
        open={proposal != null}
        projectId={projectId}
        mode="create"
        initialPrompt={proposal?.prompt ?? ""}
        onClose={() => setProposal(null)}
        onApplied={(dashboardId) => {
          const current = proposal;
          setProposal(null);
          void queryClient.invalidateQueries({
            queryKey: ["project", projectId, "dashboards"],
          });
          if (current && conversationId != null) {
            void decideArtifactProposal(conversationId, current.turnId, {
              decision: "accept",
              artifact_kind: "dashboard",
              asset_id: dashboardId,
            })
              .then(() => onSettled?.())
              .catch((error: unknown) =>
                push(
                  error instanceof Error
                    ? `Dashboard created, but chat status could not be updated: ${error.message}`
                    : "Dashboard created, but chat status could not be updated.",
                  "error",
                ),
              );
          }
        }}
        notify={push}
      />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </>
  ) : null;

  return { reviewDashboard, reviewerNode };
}
