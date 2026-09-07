"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  IconCheck,
  IconDatabase,
  IconExternalLink,
  IconLayoutDashboard,
  IconX,
} from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  decideArtifactProposal,
  type ChatArtifactProposal,
  type ConversationTurn,
} from "@/lib/api/conversational-analytics";

export function ChatArtifactConfirmationCard({
  conversationId,
  projectId,
  turn,
  onReviewDashboard,
  onDecision,
}: {
  conversationId: number;
  projectId: string;
  turn: ConversationTurn;
  onReviewDashboard?: (turnId: number, prompt: string) => void;
  onDecision?: () => void;
}) {
  const queryClient = useQueryClient();
  const [proposal, setProposal] = useState<ChatArtifactProposal | null>(
    turn.artifact_proposal ?? null,
  );

  useEffect(() => {
    setProposal(turn.artifact_proposal ?? null);
  }, [turn.artifact_proposal]);

  const decision = useMutation({
    mutationFn: (choice: "accept" | "reject") =>
      decideArtifactProposal(conversationId, turn.id, {
        decision: choice,
        artifact_kind: proposal?.kind ?? "query",
      }),
    onSuccess: (response) => {
      setProposal(response.turn.artifact_proposal ?? null);
      if (response.turn.artifact_proposal?.kind === "query") {
        void queryClient.invalidateQueries({
          queryKey: ["project", projectId, "queries"],
        });
      }
      onDecision?.();
    },
  });

  if (!proposal) return null;

  const isQuery = proposal.kind === "query";
  const accepted = proposal.status === "accepted";
  const rejected = proposal.status === "rejected";
  const Icon = isQuery ? IconDatabase : IconLayoutDashboard;

  return (
    <section
      data-testid={`${proposal.kind}-artifact-confirmation`}
      className="mt-3 overflow-hidden rounded-xl border border-ai/30 bg-ai/5"
    >
      <div className="flex items-start gap-3 px-4 py-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-bg-primary text-ai shadow-sm">
          <Icon size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-medium text-ink-primary">{proposal.title}</h3>
            <Badge tone={accepted ? "success" : rejected ? "neutral" : "ai"}>
              {accepted ? "Created" : rejected ? "Rejected" : "Pending approval"}
            </Badge>
          </div>
          <p className="mt-1 text-[12px] leading-5 text-ink-secondary">
            {proposal.description}
          </p>
          {(proposal.dataSources?.length ?? 0) > 0 && (
            <p className="mt-1 text-[11px] text-ink-tertiary">
              Grounded in {proposal.dataSources!.join(", ")}
            </p>
          )}
        </div>
      </div>

      {decision.isError && (
        <p className="border-t border-danger/20 bg-danger/5 px-4 py-2 text-[12px] text-danger">
          {decision.error instanceof Error
            ? decision.error.message
            : "The proposal could not be updated."}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-ai/20 bg-bg-primary/70 px-4 py-2.5">
        {proposal.assetUrl && accepted && (
          <a
            href={proposal.assetUrl}
            className="mr-auto inline-flex items-center gap-1 text-[12px] font-medium text-brand-600 hover:underline"
          >
            Open {proposal.kind}
            <IconExternalLink size={13} />
          </a>
        )}
        {!accepted && !rejected && (
          <>
            <Button
              size="sm"
              variant="secondary"
              disabled={decision.isPending}
              onClick={() => decision.mutate("reject")}
            >
              <IconX size={14} />
              Reject
            </Button>
            {isQuery ? (
              <Button
                size="sm"
                variant="primary"
                disabled={decision.isPending}
                onClick={() => decision.mutate("accept")}
              >
                <IconCheck size={14} />
                {decision.isPending ? "Saving…" : "Save query"}
              </Button>
            ) : (
              <Button
                size="sm"
                variant="primary"
                disabled={!onReviewDashboard}
                onClick={() => onReviewDashboard?.(turn.id, proposal.prompt)}
              >
                <IconLayoutDashboard size={14} />
                Review & create
              </Button>
            )}
          </>
        )}
      </div>
    </section>
  );
}
