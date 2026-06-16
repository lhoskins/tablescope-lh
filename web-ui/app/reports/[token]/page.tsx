"use client";

import { use, useEffect, useState } from "react";
import { IconLock, IconLoader2, IconSparkles } from "@tabler/icons-react";
import {
  getReport,
  runIntelligenceSuite,
  type InsightCard,
  type ReportRecord,
  type ReportSection,
} from "@/lib/api/home-intelligence";
import { IntelligenceCard, renderBold } from "@/components/tablescope/home/intelligence-card";

type SectionState =
  | { kind: "loading" }
  | { kind: "card"; card: InsightCard }
  | { kind: "no_access"; projectName: string }
  | { kind: "empty"; title: string };

function InsightSectionView({ section }: { section: ReportSection }) {
  const [state, setState] = useState<SectionState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const insight = section.insight;
    if (!insight) {
      setState({ kind: "empty", title: "Unknown insight" });
      return;
    }
    runIntelligenceSuite(Number(insight.projectId), [insight.insightType])
      .then((res) => {
        if (cancelled) return;
        if (res.error === "no_access") {
          setState({ kind: "no_access", projectName: insight.projectName });
          return;
        }
        const card = res.insights.find(
          (c) => c.insightType === insight.insightType,
        );
        if (card) {
          setState({ kind: "card", card });
        } else {
          setState({ kind: "empty", title: insight.title });
        }
      })
      .catch(() => {
        if (!cancelled)
          setState({ kind: "no_access", projectName: insight.projectName });
      });
    return () => {
      cancelled = true;
    };
  }, [section]);

  if (state.kind === "loading") {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-line-tertiary bg-bg-primary p-4 text-small text-ink-tertiary">
        <IconLoader2 size={15} className="animate-spin" />
        Re-running query for {section.insight?.projectName}…
      </div>
    );
  }
  if (state.kind === "no_access") {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-line-tertiary bg-bg-secondary p-4 text-small text-ink-secondary">
        <IconLock size={15} className="text-ink-tertiary" />
        You don&apos;t have access to {state.projectName}.
      </div>
    );
  }
  if (state.kind === "empty") {
    return (
      <div className="rounded-lg border border-line-tertiary bg-bg-secondary p-4 text-small text-ink-tertiary">
        {state.title}: no data available right now.
      </div>
    );
  }
  return <IntelligenceCard card={state.card} hideActions />;
}

export default function ReportViewerPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [report, setReport] = useState<ReportRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getReport(token)
      .then(setReport)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Report not found"),
      );
  }, [token]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg-secondary px-4">
        <div className="rounded-lg border border-line-tertiary bg-bg-primary p-8 text-center">
          <h1 className="text-h2 text-ink-primary">Report unavailable</h1>
          <p className="mt-2 text-small text-ink-tertiary">{error}</p>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg-secondary">
        <IconLoader2 size={24} className="animate-spin text-ink-tertiary" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg-secondary py-10">
      <div className="mx-auto w-full max-w-3xl px-5">
        <header className="mb-6 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 text-ai">
              <IconSparkles size={16} />
              <span className="text-caption uppercase tracking-wide">
                Live report
              </span>
            </div>
            <h1 className="mt-1 text-h1 text-ink-primary">{report.title}</h1>
            <p className="mt-1 text-small text-ink-tertiary">
              Queries re-run live with your own project access.
            </p>
          </div>
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded-md border border-line-tertiary bg-bg-primary px-3 py-1.5 text-small font-medium text-ink-secondary hover:bg-bg-tertiary"
          >
            Export PDF
          </button>
        </header>

        <div className="space-y-3">
          {report.sections.length === 0 && (
            <div className="rounded-lg border border-dashed border-line-secondary p-8 text-center text-small text-ink-tertiary">
              This report has no sections yet.
            </div>
          )}
          {report.sections.map((section) =>
            section.kind === "text" ? (
              <p
                key={section.id}
                className="whitespace-pre-wrap text-body text-ink-secondary"
              >
                {renderBold(section.text ?? "")}
              </p>
            ) : (
              <InsightSectionView key={section.id} section={section} />
            ),
          )}
        </div>
      </div>
    </div>
  );
}
