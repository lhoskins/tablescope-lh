"use client";

import type { ReactNode } from "react";
import { IconAlertTriangle, IconBulb, IconChartBar, IconTrendingUp } from "@tabler/icons-react";
import { IntelligenceCard } from "@/components/tablescope/home/intelligence-card";
import { InsightPanel, PanelEmpty } from "@/components/tablescope/insight-panel";
import { useReturnTarget, insightAnchorId } from "@/lib/insights/return-target";
import type { InsightCard } from "@/lib/api/home-intelligence";
import type { GovernanceItem, InsightFeedbackRecord } from "@/lib/api/insight-feedback";

export interface InsightCardActionHandlers {
  onSaveToDashboard?: (card: InsightCard) => void;
  onPin?: (card: InsightCard) => void;
  onCreateAction?: (card: InsightCard) => void;
  onFeedbackSave?: (
    card: InsightCard,
    payload: {
      sentiment: "agree" | "disagree";
      reason_codes: string[];
      comment: string;
    },
  ) => void;
  onFeedbackRemove?: (card: InsightCard) => void;
  onFeedbackRespond?: (card: InsightCard, response: string) => void;
}

export interface InsightFeedbackState {
  feedbackById: Record<string, InsightFeedbackRecord>;
  savingFeedback: boolean;
  governanceById?: Record<string, GovernanceItem>;
}

export interface InsightSectionProps {
  title: string;
  icon?: ReactNode;
  cards: InsightCard[];
  emptyText: string;
  loading?: boolean;
  defaultOpen?: boolean;
  actions?: InsightCardActionHandlers;
  feedback?: InsightFeedbackState;
  pinnedByFingerprint?: Map<string, number>;
  actionsDisclosure?: "always-visible" | "collapsible";
  children?: ReactNode;
}

const ICONS: Record<string, ReactNode> = {
  Risks: <IconAlertTriangle size={16} className="text-warning" />,
  Trends: <IconTrendingUp size={16} className="text-ink-secondary" />,
  Opportunities: <IconBulb size={16} className="text-success" />,
  "Deeper analysis": <IconChartBar size={16} className="text-brand-500" />,
};

function pinFingerprintKey(card: InsightCard): string | undefined {
  return (
    card.evidenceFingerprint?.resultFingerprint ??
    card.insightId ??
    card.id ??
    undefined
  );
}

export function InsightSection({
  title,
  icon = ICONS[title] ?? null,
  cards,
  emptyText,
  loading = false,
  defaultOpen = false,
  actions = {},
  feedback,
  pinnedByFingerprint,
  actionsDisclosure,
  children,
}: InsightSectionProps) {
  const returnTarget = useReturnTarget();
  const holdsReturnTarget =
    returnTarget != null &&
    cards.some((c) => (c.insightId || c.id) === returnTarget);

  return (
    <InsightPanel
      title={title}
      icon={icon}
      collapsible
      defaultOpen={defaultOpen || holdsReturnTarget}
      forceOpen={holdsReturnTarget}
      count={cards.length}
    >
      {cards.length === 0 ? (
        loading ? null : children ? (
          <div className="space-y-3">{children}</div>
        ) : (
          <PanelEmpty text={emptyText} />
        )
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {cards.map((card) => {
              const key = pinFingerprintKey(card) || card.insightId || card.id;
              const isPinned = Boolean(
                pinnedByFingerprint && key && pinnedByFingerprint.has(key),
              );
              const anchor = card.insightId || card.id;
              return (
                <div
                  key={key}
                  id={anchor ? insightAnchorId(anchor) : undefined}
                  className="scroll-mt-24 rounded-lg transition-shadow data-[returned=true]:ring-2 data-[returned=true]:ring-brand-500"
                >
                  <IntelligenceCard
                    card={card}
                    pinned={isPinned}
                    feedback={feedback?.feedbackById?.[card.insightId || card.id]}
                    savingFeedback={feedback?.savingFeedback}
                    governance={feedback?.governanceById?.[card.insightId || card.id]}
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
          </div>
          {children}
        </div>
      )}
    </InsightPanel>
  );
}
