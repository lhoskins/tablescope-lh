"use client";

import { useState } from "react";
import {
  IconInfoCircle,
  IconMessage,
  IconThumbDown,
  IconThumbUp,
  IconX,
} from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { InsightFeedbackRecord } from "@/lib/api/insight-feedback";
import {
  getInsightFeedbackDisplayState,
  getInsightGovernanceDisplayState,
  type FeedbackTone,
} from "@/lib/ui/insight-feedback";

export interface InsightFeedbackStatusBadgeProps {
  feedback: InsightFeedbackRecord | null | undefined;
  onClick?: () => void;
}

const toneToneMap: Record<FeedbackTone, React.ComponentProps<typeof Badge>["tone"]> = {
  success: "success",
  warning: "warning",
  brand: "brand",
  danger: "danger",
  neutral: "neutral",
  high: "warning",
};

export function InsightFeedbackStatusBadge({
  feedback,
  onClick,
}: InsightFeedbackStatusBadgeProps) {
  const state = getInsightFeedbackDisplayState(feedback);
  if (!state) return null;

  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex cursor-pointer items-center gap-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
      aria-label={`Feedback status: ${state.label}`}
      title={state.tooltip}
    >
      <Badge tone={toneToneMap[state.tone]} size="sm">
        {feedback?.sentiment === "disagree" ? (
          <IconThumbDown size={12} />
        ) : (
          <IconThumbUp size={12} />
        )}
        {state.label}
      </Badge>
    </button>
  );
}

export interface InsightGovernanceBadgeProps {
  status: string | undefined;
}

export function InsightGovernanceBadge({ status }: InsightGovernanceBadgeProps) {
  const state = getInsightGovernanceDisplayState(status);
  if (!state) return null;

  return (
    <span title={state.tooltip}>
      <Badge tone={toneToneMap[state.tone]} size="sm">
        {state.label}
      </Badge>
    </span>
  );
}

export interface InsightFeedbackStatusDialogProps {
  open: boolean;
  onClose: () => void;
  feedback: InsightFeedbackRecord | null | undefined;
  title?: string;
  onRespond?: (response: string) => void | Promise<void>;
  onEdit?: () => void;
  onWithdraw?: () => void | Promise<void>;
  responding?: boolean;
  withdrawing?: boolean;
}

export function InsightFeedbackStatusDialog({
  open,
  onClose,
  feedback,
  title,
  onRespond,
  onEdit,
  onWithdraw,
  responding,
  withdrawing,
}: InsightFeedbackStatusDialogProps) {
  const [response, setResponse] = useState("");
  const [responseError, setResponseError] = useState<string | null>(null);

  if (!open || !feedback) return null;

  const state = getInsightFeedbackDisplayState(feedback);
  const needsResponse = feedback.review_status === "needs_more_information";
  const isResolved =
    feedback.review_status === "accepted" || feedback.review_status === "rejected";

  const handleRespond = () => {
    const trimmed = response.trim();
    if (!trimmed) {
      setResponseError("Please enter a response before submitting.");
      return;
    }
    setResponseError(null);
    onRespond?.(trimmed);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="feedback-status-title"
    >
      <div
        className="my-8 w-full max-w-md rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2
              id="feedback-status-title"
              className="text-h2 text-ink-primary"
            >
              Feedback status
            </h2>
            {title && (
              <p className="mt-1 text-small text-ink-tertiary">{title}</p>
            )}
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="shrink-0 text-ink-tertiary hover:text-ink-primary"
          >
            <IconX size={18} />
          </button>
        </div>

        <div className="space-y-4 text-[13px]">
          <div className="flex items-center gap-2">
            <span className="text-ink-tertiary">Status:</span>
            {state ? (
              <Badge tone={toneToneMap[state.tone]} size="sm">
                {feedback.sentiment === "disagree" ? (
                  <IconThumbDown size={12} />
                ) : (
                  <IconThumbUp size={12} />
                )}
                {state.label}
              </Badge>
            ) : (
              <span className="text-ink-secondary">—</span>
            )}
          </div>

          <div>
            <span className="text-ink-tertiary">Submitted:</span>{" "}
            <span className="text-ink-secondary">
              {new Date(feedback.created_at).toLocaleString()}
            </span>
          </div>

          {feedback.reason_codes && feedback.reason_codes.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {feedback.reason_codes.map((code) => (
                <Badge key={code} tone="outline" size="sm">
                  {code}
                </Badge>
              ))}
            </div>
          )}

          <div>
            <span className="text-ink-tertiary">Your comment:</span>
            <p className="mt-1 rounded-md border border-line-tertiary bg-bg-secondary/30 p-2 text-ink-secondary">
              {feedback.comment || "—"}
            </p>
          </div>

          {feedback.acknowledged_at && (
            <div>
              <span className="text-ink-tertiary">Reviewer acknowledged:</span>{" "}
              <span className="text-ink-secondary">
                {new Date(feedback.acknowledged_at).toLocaleString()}
              </span>
            </div>
          )}

          {needsResponse && feedback.reviewer_comment && (
            <div>
              <span className="text-ink-tertiary">Reviewer question:</span>
              <p className="mt-1 rounded-md border border-brand-200 bg-brand-50 p-2 text-brand-700">
                <IconMessage size={14} className="mb-0.5 inline align-text-bottom" />{" "}
                {feedback.reviewer_comment}
              </p>
            </div>
          )}

          {isResolved && (
            <>
              <div>
                <span className="text-ink-tertiary">Final disposition:</span>{" "}
                <span className="font-medium text-ink-primary">
                  {feedback.review_status === "accepted" ? "Feedback Accepted" : "Insight Upheld"}
                </span>
              </div>
              {feedback.reviewer_comment && (
                <div>
                  <span className="text-ink-tertiary">Reviewer rationale:</span>
                  <p className="mt-1 rounded-md border border-line-tertiary bg-bg-secondary/30 p-2 text-ink-secondary">
                    {feedback.reviewer_comment}
                  </p>
                </div>
              )}
              {feedback.reviewed_at && (
                <div>
                  <span className="text-ink-tertiary">Reviewed at:</span>{" "}
                  <span className="text-ink-secondary">
                    {new Date(feedback.reviewed_at).toLocaleString()}
                  </span>
                </div>
              )}
            </>
          )}

          {feedback.response && (
            <div>
              <span className="text-ink-tertiary">Your response:</span>
              <p className="mt-1 rounded-md border border-line-tertiary bg-bg-secondary/30 p-2 text-ink-secondary">
                {feedback.response}
              </p>
            </div>
          )}

          {needsResponse && (
            <div>
              <label className="mb-1.5 block text-small font-medium text-ink-secondary">
                Your response <span className="text-danger">*</span>
              </label>
              <textarea
                value={response}
                onChange={(e) => {
                  setResponse(e.target.value);
                  if (responseError && e.target.value.trim()) {
                    setResponseError(null);
                  }
                }}
                rows={3}
                maxLength={4000}
                className={`w-full rounded-md border bg-bg-primary px-3 py-2 text-[13px] text-ink-primary focus:outline-none ${
                  responseError
                    ? "border-danger focus:border-danger"
                    : "border-line-secondary focus:border-brand-500"
                }`}
                placeholder="Add the details the reviewer requested…"
                autoFocus
              />
              {responseError && (
                <p className="mt-1 text-[12px] text-danger">{responseError}</p>
              )}
            </div>
          )}

          <div className="rounded-md border border-brand-200 bg-brand-50 px-3 py-2 text-[12px] text-brand-700">
            <IconInfoCircle size={14} className="mb-0.5 inline align-text-bottom" />{" "}
            Your feedback is used to improve insight quality and is not shown to other
            project members except reviewers.
          </div>
        </div>

        <div className="mt-5 flex items-center justify-between border-t border-line-tertiary pt-4">
          <div className="flex gap-2">
            {!isResolved && onEdit && (
              <Button variant="secondary" size="sm" onClick={onEdit}>
                Edit feedback
              </Button>
            )}
            {onWithdraw && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void onWithdraw()}
                disabled={withdrawing}
              >
                {withdrawing ? "Withdrawing…" : "Withdraw"}
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              Close
            </Button>
            {needsResponse && onRespond && (
              <Button
                variant="primary"
                size="sm"
                onClick={handleRespond}
                disabled={!response.trim() || responding}
              >
                {responding ? "Submitting…" : "Submit response"}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
