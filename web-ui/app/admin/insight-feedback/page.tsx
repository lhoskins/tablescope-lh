"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getInsightFeedbackReview,
  type InsightFeedbackReviewItem,
  INSIGHT_FEEDBACK_REASON_CODES,
} from "@/lib/api/insight-feedback";

const PAGE_SIZE = 25;

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const positive = sentiment === "agree";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
        positive
          ? "bg-emerald-50 text-emerald-700"
          : "bg-rose-50 text-rose-700"
      }`}
    >
      {sentiment === "agree" ? "Agree" : "Disagree"}
    </span>
  );
}

export default function InsightFeedbackReviewPage() {
  const [sentiment, setSentiment] = useState<string>("");
  const [page, setPage] = useState(0);

  const query = useQuery({
    queryKey: ["insight-feedback-review", sentiment, page],
    queryFn: () =>
      getInsightFeedbackReview({
        sentiment: sentiment || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  });

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  const reasonLabels = useMemo(() => INSIGHT_FEEDBACK_REASON_CODES, []);

  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900">Insight Review</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Review Agree/Disagree feedback on AI-generated insights across projects.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-xs text-slate-500">
          Sentiment
          <select
            value={sentiment}
            onChange={(e) => {
              setSentiment(e.target.value);
              setPage(0);
            }}
            className="mt-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">All</option>
            <option value="agree">Agree</option>
            <option value="disagree">Disagree</option>
          </select>
        </label>
      </div>

      {query.isLoading && <p className="text-sm text-slate-500">Loading feedback…</p>}
      {query.error && (
        <p className="text-sm text-red-600">{(query.error as Error).message}</p>
      )}

      <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                Time
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                User
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                Project
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                Sentiment
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                Insight
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                Reasons
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                Comment
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((item: InsightFeedbackReviewItem) => (
              <tr key={item.id} className="hover:bg-slate-50">
                <td className="whitespace-nowrap px-4 py-3 text-sm text-slate-600">
                  {new Date(item.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-sm text-slate-900">{item.user_email}</td>
                <td className="px-4 py-3 text-sm text-slate-600">
                  {item.project_name ?? `Project #${item.project_id}`}
                </td>
                <td className="px-4 py-3">
                  <SentimentBadge sentiment={item.sentiment} />
                </td>
                <td className="px-4 py-3 text-sm text-slate-900">
                  {item.card_title ?? item.insight_id}
                </td>
                <td className="px-4 py-3 text-sm text-slate-600">
                  {item.reason_codes.length > 0
                    ? item.reason_codes.map((code) => reasonLabels[code] ?? code).join(", ")
                    : "—"}
                </td>
                <td className="max-w-xs px-4 py-3 text-sm text-slate-600">
                  {item.comment ?? "—"}
                </td>
              </tr>
            ))}
            {items.length === 0 && !query.isLoading && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-sm text-slate-500">
                  No feedback matches the selected filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-slate-500">
          <span>
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              onClick={() =>
                setPage((p) =>
                  (p + 1) * PAGE_SIZE < total ? p + 1 : p,
                )
              }
              disabled={(page + 1) * PAGE_SIZE >= total}
              className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
