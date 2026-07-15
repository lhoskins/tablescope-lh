"use client";

import { useEffect, useState } from "react";
import {
  IconX,
  IconThumbUp,
  IconThumbDown,
  IconTrash,
  IconInfoCircle,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import type { InsightCard } from "@/lib/api/home-intelligence";
import type { InsightFeedbackRecord, InsightSentiment } from "@/lib/api/insight-feedback";
import {
  INSIGHT_FEEDBACK_REASON_CODES,
} from "@/lib/api/insight-feedback";

export interface InsightFeedbackDialogProps {
  card: InsightCard;
  open: boolean;
  onClose: () => void;
  /** The current feedback record for this insight, if any. */
  feedback: InsightFeedbackRecord | null;
  onSave: (payload: {
    sentiment: InsightSentiment;
    reason_codes: string[];
    comment: string;
  }) => void | Promise<void>;
  onRemove: () => void | Promise<void>;
  /** Whether the save/remove mutation is in flight. */
  saving?: boolean;
}

export function InsightFeedbackDialog({
  card,
  open,
  onClose,
  feedback,
  onSave,
  onRemove,
  saving = false,
}: InsightFeedbackDialogProps) {
  const [sentiment, setSentiment] = useState<InsightSentiment>("agree");
  const [reasonCodes, setReasonCodes] = useState<string[]>([]);
  const [comment, setComment] = useState("");

  useEffect(() => {
    if (!open) return;
    setSentiment((feedback?.sentiment as InsightSentiment) || "agree");
    setReasonCodes(feedback?.reason_codes ?? []);
    setComment(feedback?.comment ?? "");
  }, [open, feedback?.sentiment, feedback?.reason_codes, feedback?.comment]);

  if (!open) return null;

  const toggleReason = (code: string) => {
    setReasonCodes((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code],
    );
  };

  const canSave = sentiment === "agree" || sentiment === "disagree";
  const hasExisting = feedback != null && feedback.status === "active";

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="insight-feedback-title"
    >
      <div
        className="my-8 w-full max-w-md rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2
              id="insight-feedback-title"
              className="text-h2 text-ink-primary"
            >
              Your feedback
            </h2>
            <p className="mt-1 text-small text-ink-tertiary">
              {card.title}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="shrink-0 text-ink-tertiary hover:text-ink-primary"
            disabled={saving}
          >
            <IconX size={18} />
          </button>
        </div>

        <div className="rounded-md border border-brand-200 bg-brand-50 px-3 py-2 text-[12px] text-brand-700">
          <IconInfoCircle size={14} className="mb-0.5 inline align-text-bottom" />{" "}
          Your feedback is saved to improve future insight quality. It does not
          immediately change this insight or automatically retrain the AI.
        </div>

        <div className="mt-5">
          <label className="mb-2 block text-small font-medium text-ink-secondary">
            Do you agree with this insight?
          </label>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setSentiment("agree")}
              aria-pressed={sentiment === "agree"}
              className={`flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-[13px] font-medium transition ${
                sentiment === "agree"
                  ? "border-success bg-success/10 text-success"
                  : "border-line-secondary bg-bg-secondary text-ink-secondary hover:border-line-primary"
              }`}
            >
              <IconThumbUp size={16} />
              Agree
            </button>
            <button
              type="button"
              onClick={() => setSentiment("disagree")}
              aria-pressed={sentiment === "disagree"}
              className={`flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-[13px] font-medium transition ${
                sentiment === "disagree"
                  ? "border-danger bg-danger/10 text-danger"
                  : "border-line-secondary bg-bg-secondary text-ink-secondary hover:border-line-primary"
              }`}
            >
              <IconThumbDown size={16} />
              Disagree
            </button>
          </div>
        </div>

        {sentiment === "disagree" && (
          <div className="mt-4">
            <label className="mb-2 block text-small font-medium text-ink-secondary">
              Reasons (optional)
            </label>
            <div className="space-y-2">
              {Object.entries(INSIGHT_FEEDBACK_REASON_CODES).map(([code, label]) => (
                <label
                  key={code}
                  className="flex items-start gap-2 rounded-md border border-line-tertiary bg-bg-secondary/30 px-2.5 py-2 text-[13px] text-ink-secondary"
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={reasonCodes.includes(code)}
                    onChange={() => toggleReason(code)}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="mt-4">
          <label className="mb-1.5 block text-small font-medium text-ink-secondary">
            Comment (optional)
          </label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="What would make this insight more useful?"
            rows={3}
            maxLength={4000}
            className="w-full rounded-md border border-line-secondary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="mt-5 flex items-center justify-between border-t border-line-tertiary pt-4">
          {hasExisting ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={saving}
              onClick={() => void onRemove()}
            >
              <IconTrash size={14} />
              Remove
            </Button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" disabled={saving} onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!canSave || saving}
              onClick={() =>
                void onSave({
                  sentiment,
                  reason_codes: sentiment === "disagree" ? reasonCodes : [],
                  comment,
                })
              }
            >
              {saving ? "Saving…" : hasExisting ? "Update" : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
