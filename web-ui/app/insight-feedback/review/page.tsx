"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconCheck,
  IconRefresh,
  IconTrash,
  IconThumbDown,
  IconThumbUp,
  IconX,
} from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getUserMeta } from "@/lib/auth";
import {
  claimInsightFeedbackReview,
  dispositionInsightFeedbackReview,
  getInsightFeedbackReviewQueue,
  releaseInsightFeedbackReview,
  type InsightFeedbackReviewItem,
} from "@/lib/api/insight-feedback";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import type { CurrentUser, NavKey, TenantSummary } from "@/lib/ui/types";

const FALLBACK_USER: CurrentUser = {
  name: "",
  email: "",
  role: "",
  tenantName: "",
  initials: "··",
};

const FALLBACK_TENANT: TenantSummary = {
  name: "Tablescope",
  slug: "",
  initials: "TS",
};

const REVIEW_PERMISSION = "insight_feedback.review";

function isInsightReviewer(user: CurrentUser): boolean {
  if (user.permissions?.includes(REVIEW_PERMISSION)) return true;
  return ["admin", "tenant_admin", "root_admin"].includes(user.rawRole ?? "");
}

function sentimentBadge(sentiment: string) {
  if (sentiment === "agree") {
    return (
      <Badge tone="success" className="gap-1">
        <IconThumbUp size={12} /> Agree
      </Badge>
    );
  }
  if (sentiment === "disagree") {
    return (
      <Badge tone="danger" className="gap-1">
        <IconThumbDown size={12} /> Disagree
      </Badge>
    );
  }
  return <Badge tone="neutral">{sentiment}</Badge>;
}

function reviewStatusBadge(status: string) {
  switch (status) {
    case "accepted":
      return <Badge tone="success">Accepted</Badge>;
    case "rejected":
      return <Badge tone="danger">Rejected</Badge>;
    case "needs_more_information":
      return <Badge tone="warning">Needs more info</Badge>;
    default:
      return <Badge tone="neutral">Pending</Badge>;
  }
}

export default function InsightFeedbackReviewPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: identity } = useCurrentUser();
  const [reviewStatus, setReviewStatus] = useState("");
  const [sentiment, setSentiment] = useState("");
  const [selected, setSelected] = useState<InsightFeedbackReviewItem | null>(null);
  const [disposition, setDisposition] = useState("accepted");
  const [reviewerComment, setReviewerComment] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  const filters = useMemo(
    () => ({
      review_status: reviewStatus || undefined,
      sentiment: sentiment || undefined,
    }),
    [reviewStatus, sentiment],
  );

  const { data: queue, isLoading, error } = useQuery({
    queryKey: ["insight-feedback", "review", filters],
    queryFn: () => getInsightFeedbackReviewQueue(filters),
    enabled: isInsightReviewer(user),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["insight-feedback", "review"] });
  };

  const handleClaim = async (id: number) => {
    setActionError(null);
    try {
      await claimInsightFeedbackReview(id);
      refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Claim failed");
    }
  };

  const handleRelease = async (id: number) => {
    setActionError(null);
    try {
      await releaseInsightFeedbackReview(id);
      refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Release failed");
    }
  };

  const handleDisposition = async () => {
    if (!selected) return;
    if (!reviewerComment.trim()) {
      setActionError("A reviewer comment is required for final dispositions.");
      return;
    }
    setActionError(null);
    try {
      await dispositionInsightFeedbackReview(selected.id, {
        review_status: disposition,
        reviewer_comment: reviewerComment.trim(),
      });
      setSelected(null);
      setReviewerComment("");
      refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Disposition failed");
    }
  };

  if (!isInsightReviewer(user)) {
    return (
      <AppShell
        mode="home"
        activeNav={"insight-feedback-review" as NavKey}
        tenant={tenant}
        user={user}
      >
        <div className="rounded-lg border border-line-tertiary bg-bg-primary p-8 text-center">
          <h1 className="text-h2 text-ink-primary">Insight Review</h1>
          <p className="mt-2 text-body text-ink-secondary">
            You do not have permission to review insight feedback.
          </p>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      mode="home"
      activeNav="insight-feedback-review"
      tenant={tenant}
      user={user}
      topBarLeft={<span className="text-[15px] text-ink-secondary">Insight Review</span>}
      topBarRight={
        <Button variant="secondary" size="md" onClick={refresh} disabled={isLoading}>
          <IconRefresh size={15} className={isLoading ? "animate-spin" : ""} />
          Refresh
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={reviewStatus}
            onChange={(e) => setReviewStatus(e.target.value)}
            className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary"
          >
            <option value="">All review statuses</option>
            <option value="pending">Pending</option>
            <option value="accepted">Accepted</option>
            <option value="rejected">Rejected</option>
            <option value="needs_more_information">Needs more information</option>
          </select>
          <select
            value={sentiment}
            onChange={(e) => setSentiment(e.target.value)}
            className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary"
          >
            <option value="">All sentiments</option>
            <option value="agree">Agree</option>
            <option value="disagree">Disagree</option>
          </select>
          <span className="text-small text-ink-tertiary">
            {queue?.total ?? 0} item{queue?.total === 1 ? "" : "s"}
          </span>
        </div>

        {actionError && (
          <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-small text-danger">
            {actionError}
          </div>
        )}

        {error && (
          <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-small text-danger">
            {error instanceof Error ? error.message : "Could not load review queue."}
          </div>
        )}

        <div className="overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-line-tertiary bg-bg-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                <th className="px-4 py-2.5 font-medium">Insight</th>
                <th className="px-4 py-2.5 font-medium">Project</th>
                <th className="px-4 py-2.5 font-medium">Sentiment</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Submitted</th>
                <th className="px-4 py-2.5 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink-tertiary">
                    Loading…
                  </td>
                </tr>
              )}
              {!isLoading && (queue?.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink-tertiary">
                    No feedback awaiting review.
                  </td>
                </tr>
              )}
              {queue?.items.map((item) => (
                <tr
                  key={item.id}
                  className="cursor-pointer border-b border-line-tertiary last:border-0 hover:bg-bg-tertiary"
                  onClick={() => {
                    setSelected(item);
                    setReviewerComment(item.reviewer_comment ?? "");
                    setDisposition(item.review_status || "accepted");
                    setActionError(null);
                  }}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-ink-primary max-w-xs truncate">
                      {item.insight_id}
                    </div>
                    {item.comment && (
                      <div className="mt-0.5 max-w-md text-[12px] text-ink-secondary line-clamp-2">
                        {item.comment}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-ink-secondary">{item.project_id ?? "—"}</td>
                  <td className="px-4 py-3">{sentimentBadge(item.sentiment)}</td>
                  <td className="px-4 py-3">{reviewStatusBadge(item.review_status || "pending")}</td>
                  <td className="px-4 py-3 text-ink-secondary">
                    {new Date(item.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex justify-end gap-2">
                      {item.review_status === "pending" && item.reviewer_user_id == null && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleClaim(item.id)}
                        >
                          Claim
                        </Button>
                      )}
                      {item.reviewer_user_id != null && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRelease(item.id)}
                        >
                          Release
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selected && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4"
          onClick={() => setSelected(null)}
        >
          <div
            className="my-8 w-full max-w-lg rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-h2 text-ink-primary">Review feedback</h2>
                <p className="mt-1 text-small text-ink-tertiary">
                  {selected.insight_id}
                </p>
              </div>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setSelected(null)}
                className="shrink-0 text-ink-tertiary hover:text-ink-primary"
              >
                <IconX size={18} />
              </button>
            </div>

            <div className="space-y-3 text-[13px]">
              <div className="flex items-center gap-2">
                <span className="text-ink-tertiary">Sentiment:</span>
                {sentimentBadge(selected.sentiment)}
              </div>
              <div>
                <span className="text-ink-tertiary">User comment:</span>
                <p className="mt-1 rounded-md border border-line-tertiary bg-bg-secondary p-2 text-ink-secondary">
                  {selected.comment || "—"}
                </p>
              </div>
              {selected.reason_codes && selected.reason_codes.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {selected.reason_codes.map((code) => (
                    <Badge key={code} tone="outline">
                      {code}
                    </Badge>
                  ))}
                </div>
              )}

              <div>
                <label className="mb-1.5 block text-small font-medium text-ink-secondary">
                  Disposition
                </label>
                <select
                  value={disposition}
                  onChange={(e) => setDisposition(e.target.value)}
                  className="w-full rounded-md border border-line-tertiary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary"
                >
                  <option value="accepted">Accepted</option>
                  <option value="rejected">Rejected</option>
                  <option value="needs_more_information">Needs more information</option>
                </select>
              </div>

              <div>
                <label className="mb-1.5 block text-small font-medium text-ink-secondary">
                  Reviewer comment <span className="text-danger">*</span>
                </label>
                <textarea
                  value={reviewerComment}
                  onChange={(e) => setReviewerComment(e.target.value)}
                  rows={3}
                  maxLength={4000}
                  className="w-full rounded-md border border-line-secondary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary focus:border-brand-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="mt-5 flex items-center justify-between border-t border-line-tertiary pt-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleRelease(selected.id)}
              >
                <IconTrash size={14} /> Release
              </Button>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" onClick={() => setSelected(null)}>
                  Cancel
                </Button>
                <Button variant="primary" size="sm" onClick={handleDisposition}>
                  <IconCheck size={14} /> Save disposition
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
