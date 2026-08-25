"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  IconAlertTriangle,
  IconArrowRight,
  IconBriefcase,
  IconBulb,
  IconFileText,
  IconSparkles,
  IconTrendingUp,
} from "@tabler/icons-react";

import { IntelligenceCard } from "@/components/tablescope/home/intelligence-card";
import { PercentChangeSummaryPanel } from "@/components/tablescope/home/percent-change-summary-panel";
import {
  IntelligenceStrip,
  type IntelligenceStripProps,
} from "@/components/tablescope/home/intelligence-strip";
import { PanelEmpty } from "@/components/tablescope/insight-panel";
import { cn } from "@/lib/cn";
import { classifyInsightCards } from "@/lib/insights/classify-insight-cards";
import { insightAnchorId, useReturnTarget } from "@/lib/insights/return-target";
import type {
  CrossProjectSynthesis,
  InsightCard,
} from "@/lib/api/home-intelligence";

import type {
  InsightCardActionHandlers,
  InsightFeedbackState,
} from "./insight-section";

type BusinessInsightTab =
  | "overview"
  | "risks"
  | "trends"
  | "opportunities"
  | "change"
  | "analysis";

interface BusinessIntelligenceWorkspaceProps {
  projectIds: number[];
  cards: InsightCard[];
  running: boolean;
  lastUpdated: Date | null;
  snapshotFingerprint?: string | null;
  toolbar: IntelligenceStripProps;
  actions: InsightCardActionHandlers;
  feedback: InsightFeedbackState;
  emptyMessages: {
    risks: string;
    trends: string;
    opportunities: string;
    analysis: string;
  };
  pinnedByFingerprint?: Map<string, number>;
  emptySelection?: ReactNode;
  empty?: ReactNode;
  analysisChildren?: ReactNode;
  actionsDisclosure?: "always-visible" | "collapsible";
  showToolbar?: boolean;
  synthesis?: CrossProjectSynthesis | null;
  /** Page title block rendered on the same row as the toolbar. */
  header?: ReactNode;
}

const TABS: Array<{ id: BusinessInsightTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "risks", label: "Risks" },
  { id: "trends", label: "Trends" },
  { id: "opportunities", label: "Opportunities" },
  { id: "change", label: "Change summary" },
  { id: "analysis", label: "Deeper analysis" },
];

function pinFingerprintKey(card: InsightCard): string | undefined {
  return (
    card.evidenceFingerprint?.resultFingerprint ??
    card.insightId ??
    card.id ??
    undefined
  );
}

function InsightGrid({
  cards,
  emptyText,
  loading,
  actions,
  feedback,
  pinnedByFingerprint,
  actionsDisclosure,
  children,
}: {
  cards: InsightCard[];
  emptyText: string;
  loading: boolean;
  actions: InsightCardActionHandlers;
  feedback: InsightFeedbackState;
  pinnedByFingerprint?: Map<string, number>;
  actionsDisclosure?: "always-visible" | "collapsible";
  children?: ReactNode;
}) {
  const returnTarget = useReturnTarget();

  if (cards.length === 0) {
    if (loading) return null;
    if (children) return <div className="space-y-4">{children}</div>;
    return <PanelEmpty text={emptyText} />;
  }

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      {cards.map((card) => {
        const key = pinFingerprintKey(card) || card.insightId || card.id;
        const anchor = card.insightId || card.id;
        const isPinned = Boolean(
          pinnedByFingerprint && key && pinnedByFingerprint.has(key),
        );

        return (
          <div
            key={key}
            id={anchor ? insightAnchorId(anchor) : undefined}
            data-returned={Boolean(anchor && returnTarget === anchor)}
            className="scroll-mt-24 rounded-xl transition-shadow data-[returned=true]:ring-2 data-[returned=true]:ring-brand-500"
          >
            <IntelligenceCard
              card={card}
              presentation="executive"
              pinned={isPinned}
              feedback={feedback.feedbackById?.[card.insightId || card.id]}
              savingFeedback={feedback.savingFeedback}
              governance={feedback.governanceById?.[card.insightId || card.id]}
              onSaveToDashboard={actions.onSaveToDashboard}
              onPin={actions.onPin}
              onCreateAction={
                actions.onCreateAction
                  ? () => actions.onCreateAction!(card)
                  : undefined
              }
              onFeedbackSave={
                actions.onFeedbackSave
                  ? (payload) => actions.onFeedbackSave!(card, payload)
                  : undefined
              }
              onFeedbackRemove={
                actions.onFeedbackRemove
                  ? () => actions.onFeedbackRemove!(card)
                  : undefined
              }
              onFeedbackRespond={
                actions.onFeedbackRespond
                  ? (response) => actions.onFeedbackRespond!(card, response)
                  : undefined
              }
              actionsDisclosure={actionsDisclosure}
            />
          </div>
        );
      })}
      {children && <div className="xl:col-span-2">{children}</div>}
    </div>
  );
}

function PageHeading({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-h1 text-ink-primary">{title}</h2>
      <p className="mt-1 text-body text-ink-tertiary">{description}</p>
    </div>
  );
}

export function BusinessIntelligenceWorkspace({
  projectIds,
  cards,
  running,
  lastUpdated,
  snapshotFingerprint,
  toolbar,
  actions,
  feedback,
  emptyMessages,
  pinnedByFingerprint,
  emptySelection,
  empty,
  analysisChildren,
  actionsDisclosure,
  showToolbar = true,
  synthesis,
  header,
}: BusinessIntelligenceWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<BusinessInsightTab>("overview");
  const returnTarget = useReturnTarget();
  const { risks, trends, opportunities, analysis } = useMemo(
    () => classifyInsightCards(cards),
    [cards],
  );
  const fingerprint =
    snapshotFingerprint ?? (lastUpdated ? lastUpdated.toISOString() : null);
  const hasDeeperAnalysis = analysis.length > 0 || Boolean(analysisChildren);
  const visibleTabs = useMemo(
    () => TABS.filter((tab) => tab.id !== "analysis" || hasDeeperAnalysis),
    [hasDeeperAnalysis],
  );

  useEffect(() => {
    if (!returnTarget) return;
    if (risks.some((card) => (card.insightId || card.id) === returnTarget)) {
      setActiveTab("risks");
    } else if (
      trends.some((card) => (card.insightId || card.id) === returnTarget)
    ) {
      setActiveTab("trends");
    } else if (
      opportunities.some((card) => (card.insightId || card.id) === returnTarget)
    ) {
      setActiveTab("opportunities");
    } else if (
      analysis.some((card) => (card.insightId || card.id) === returnTarget)
    ) {
      setActiveTab("analysis");
    }
  }, [analysis, opportunities, returnTarget, risks, trends]);

  const counts: Record<BusinessInsightTab, number | null> = {
    overview: null,
    risks: risks.length,
    trends: trends.length,
    opportunities: opportunities.length,
    change: null,
    analysis: analysis.length,
  };

  const developments = [
    risks[0]
      ? {
          card: risks[0],
          label: "Risk",
          tab: "risks" as const,
          icon: <IconAlertTriangle size={17} />,
        }
      : null,
    trends[0]
      ? {
          card: trends[0],
          label: "Trend",
          tab: "trends" as const,
          icon: <IconTrendingUp size={17} />,
        }
      : null,
    opportunities[0]
      ? {
          card: opportunities[0],
          label: "Opportunity",
          tab: "opportunities" as const,
          icon: <IconBulb size={17} />,
        }
      : null,
    analysis[0]
      ? {
          card: analysis[0],
          label: "Analysis",
          tab: "analysis" as const,
          icon: <IconFileText size={17} />,
        }
      : null,
  ].filter((item): item is NonNullable<typeof item> => item !== null);

  const priorities = [
    risks[0]
      ? {
          card: risks[0],
          label: `Risk · ${risks[0].severity}`,
          tab: "risks" as const,
        }
      : null,
    trends[0]
      ? { card: trends[0], label: "Trend · watch", tab: "trends" as const }
      : null,
    opportunities[0]
      ? {
          card: opportunities[0],
          label: "Opportunity",
          tab: "opportunities" as const,
        }
      : null,
  ].filter((item): item is NonNullable<typeof item> => item !== null);

  const cardGridProps = {
    loading: running,
    actions,
    feedback,
    pinnedByFingerprint,
    actionsDisclosure,
  };

  return (
    <div className="space-y-5">
      {showToolbar && (
        <div className="flex flex-wrap items-start justify-between gap-4">
          {header}
          <IntelligenceStrip {...toolbar} scope="business" />
        </div>
      )}

      <div
        className="flex flex-wrap items-center gap-x-7 gap-y-2 border-b border-line-tertiary"
        role="tablist"
        aria-label="Business Insight sections"
      >
        {visibleTabs.map((tab) => {
          const selected = activeTab === tab.id;
          const count = counts[tab.id];
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`business-insight-tab-${tab.id}`}
              aria-controls={`business-insight-panel-${tab.id}`}
              aria-selected={selected}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "-mb-px inline-flex items-center gap-2 border-b-2 px-1 pb-3 pt-1 text-body font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500",
                selected
                  ? "border-brand-500 text-ink-primary"
                  : "border-transparent text-ink-tertiary hover:text-ink-secondary",
              )}
            >
              {tab.label}
              {count != null && count > 0 && (
                <span className="rounded-full bg-bg-tertiary px-2 py-0.5 text-[11px] text-ink-secondary">
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {projectIds.length === 0 && !running && (emptySelection ?? empty)}

      {projectIds.length > 0 && activeTab === "overview" && (
        <section
          id="business-insight-panel-overview"
          role="tabpanel"
          aria-labelledby="business-insight-tab-overview"
          className="space-y-5"
        >
          <section className="rounded-2xl border border-line-secondary bg-[#E5E5E5] px-5 py-6 shadow-sm">
            <div className="flex items-center gap-2 text-caption font-medium uppercase tracking-wide text-ink-tertiary">
              <IconBriefcase size={16} />
              Executive brief
            </div>
            <h2 className="mt-3 max-w-5xl text-[24px] font-semibold leading-tight text-ink-primary">
              {synthesis?.headline ??
                "Business intelligence is ready for executive review"}
            </h2>
            <p className="mt-2 max-w-5xl text-body leading-6 text-ink-secondary">
              {synthesis?.body ??
                "Review the highest-materiality risks, durable trends, and evidence-backed opportunities from the selected projects."}
            </p>
            <button
              type="button"
              onClick={() =>
                setActiveTab(risks.length > 0 ? "risks" : "trends")
              }
              className="mt-4 inline-flex items-center gap-1.5 text-body font-medium text-ink-primary hover:text-brand-600"
            >
              Review supporting evidence
              <IconArrowRight size={16} />
            </button>
          </section>

          {developments.length > 0 && (
            <section className="rounded-xl border border-line-tertiary bg-bg-primary px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-h2 text-ink-primary">Key developments</h2>
                  <p className="mt-1 text-body text-ink-tertiary">
                    Ranked by materiality and freshness
                  </p>
                </div>
                <span className="rounded-full bg-brand-50 px-2.5 py-1 text-[11px] font-medium text-brand-700">
                  AI ranked
                </span>
              </div>
              <div className="mt-3">
                {developments.map((item) => (
                  <button
                    key={`${item.label}-${item.card.insightId || item.card.id}`}
                    type="button"
                    onClick={() => setActiveTab(item.tab)}
                    className="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-t border-line-tertiary px-1 py-3 text-left first:border-t-0 hover:bg-bg-secondary/60"
                  >
                    <span className="text-ink-tertiary">{item.icon}</span>
                    <span className="min-w-0">
                      <span className="block truncate text-body font-medium text-ink-primary">
                        {item.card.title}
                      </span>
                      <span className="mt-0.5 block truncate text-small text-ink-tertiary">
                        {item.card.projectName} · {item.label}
                      </span>
                    </span>
                    <span className="text-small text-ink-tertiary">
                      {item.card.severity}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {priorities.length > 0 && (
            <section>
              <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-h2 text-ink-primary">Priority insights</h2>
                  <p className="mt-1 text-body text-ink-tertiary">
                    The findings most likely to affect a decision
                  </p>
                </div>
                <span className="text-small text-ink-tertiary">
                  {cards.length} total insights
                </span>
              </div>
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                {priorities.map((item) => (
                  <button
                    key={`${item.label}-${item.card.insightId || item.card.id}`}
                    type="button"
                    onClick={() => setActiveTab(item.tab)}
                    className="group rounded-xl border border-line-tertiary bg-[#F0F0F1] p-4 text-left transition-colors hover:border-line-secondary hover:bg-bg-secondary focus:outline-none focus:ring-2 focus:ring-brand-500"
                  >
                    <span className="text-caption font-medium uppercase tracking-wide text-ink-tertiary">
                      {item.label}
                    </span>
                    <span className="mt-2 block text-h3 text-ink-primary">
                      {item.card.title}
                    </span>
                    <span className="mt-2 line-clamp-3 text-body text-ink-secondary">
                      {item.card.summary}
                    </span>
                    <span className="mt-4 inline-flex items-center gap-1 text-small font-medium text-ink-primary">
                      Review insight <IconArrowRight size={14} />
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

        </section>
      )}

      {projectIds.length > 0 && activeTab === "risks" && (
        <section
          id="business-insight-panel-risks"
          role="tabpanel"
          aria-labelledby="business-insight-tab-risks"
        >
          <PageHeading
            title="Risks"
            description="Decision-relevant issues ranked by severity, materiality, and freshness."
          />
          <InsightGrid
            cards={risks}
            emptyText={emptyMessages.risks}
            {...cardGridProps}
          />
        </section>
      )}

      {projectIds.length > 0 && activeTab === "trends" && (
        <section
          id="business-insight-panel-trends"
          role="tabpanel"
          aria-labelledby="business-insight-tab-trends"
        >
          <PageHeading
            title="Trends"
            description="Persistent movement separated from one-period noise."
          />
          <InsightGrid
            cards={trends}
            emptyText={emptyMessages.trends}
            {...cardGridProps}
          />
        </section>
      )}

      {projectIds.length > 0 && activeTab === "opportunities" && (
        <section
          id="business-insight-panel-opportunities"
          role="tabpanel"
          aria-labelledby="business-insight-tab-opportunities"
        >
          <PageHeading
            title="Opportunities"
            description="Evidence-backed improvements ranked by expected impact and confidence."
          />
          <InsightGrid
            cards={opportunities}
            emptyText={emptyMessages.opportunities}
            {...cardGridProps}
          />
        </section>
      )}

      {projectIds.length > 0 && activeTab === "analysis" && (
        <section
          id="business-insight-panel-analysis"
          role="tabpanel"
          aria-labelledby="business-insight-tab-analysis"
        >
          <PageHeading
            title="Deeper analysis"
            description="Diagnostic findings that inform the executive brief but aren't a risk, trend, or opportunity on their own."
          />
          <InsightGrid
            cards={analysis}
            emptyText={emptyMessages.analysis}
            {...cardGridProps}
          >
            {analysisChildren}
          </InsightGrid>
        </section>
      )}

      {projectIds.length > 0 && activeTab === "change" && (
        <section
          id="business-insight-panel-change"
          role="tabpanel"
          aria-labelledby="business-insight-tab-change"
        >
          <PageHeading
            title="Change summary"
            description="Period-over-period movement across eligible insight measures."
          />
          <PercentChangeSummaryPanel
            projectIds={projectIds}
            snapshotFingerprint={fingerprint}
            presentation="executive"
          />
        </section>
      )}

      {projectIds.length > 0 && cards.length === 0 && !running && empty}
      {running && cards.length === 0 && (
        <div className="flex items-center gap-2 rounded-xl border border-line-tertiary bg-bg-primary p-5 text-body text-ink-tertiary">
          <IconSparkles size={18} className="animate-pulse text-brand-500" />
          Building the executive briefing…
        </div>
      )}
    </div>
  );
}
