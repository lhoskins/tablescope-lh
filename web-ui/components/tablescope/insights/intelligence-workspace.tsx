"use client";

import type { ReactNode } from "react";
import {
  IconAlertTriangle,
  IconBulb,
  IconChartBar,
  IconTrendingUp,
} from "@tabler/icons-react";
import { IntelligenceStrip, type IntelligenceStripProps } from "@/components/tablescope/home/intelligence-strip";
import { PercentChangeSummaryPanel } from "@/components/tablescope/home/percent-change-summary-panel";
import {
  InsightSection,
  type InsightCardActionHandlers,
  type InsightFeedbackState,
} from "./insight-section";
import { classifyInsightCards } from "@/lib/insights/classify-insight-cards";
import { useReturnTarget, useScrollToReturnTarget } from "@/lib/insights/return-target";
import type {
  CrossProjectSynthesis,
  InsightCard,
} from "@/lib/api/home-intelligence";
import { BusinessIntelligenceWorkspace } from "./business-intelligence-workspace";

export type IntelligenceWorkspaceToolbar = IntelligenceStripProps;

export interface IntelligenceEmptyMessages {
  risks: string;
  trends: string;
  opportunities: string;
  analysis: string;
}

export interface IntelligenceWorkspaceProps {
  scope: "business" | "project";
  projectIds: number[];
  cards: InsightCard[];
  running: boolean;
  lastUpdated: Date | null;
  snapshotFingerprint?: string | null;
  toolbar: IntelligenceWorkspaceToolbar;
  actions: InsightCardActionHandlers;
  feedback: InsightFeedbackState;
  emptyMessages: IntelligenceEmptyMessages;
  pinnedByFingerprint?: Map<string, number>;
  emptySelection?: ReactNode;
  empty?: ReactNode;
  analysisChildren?: ReactNode;
  actionsDisclosure?: "always-visible" | "collapsible";
  showToolbar?: boolean;
  presentation?: "default" | "executive";
  synthesis?: CrossProjectSynthesis | null;
}

export function IntelligenceWorkspace({
  scope,
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
  presentation = "default",
  synthesis = null,
}: IntelligenceWorkspaceProps) {
  const { risks, trends, opportunities, analysis } = classifyInsightCards(cards);
  const hasCards = cards.length > 0;
  const returnTarget = useReturnTarget();
  const fingerprint = snapshotFingerprint ?? (lastUpdated ? lastUpdated.toISOString() : null);

  useScrollToReturnTarget(returnTarget, hasCards);

  if (scope === "business" && presentation === "executive") {
    return (
      <BusinessIntelligenceWorkspace
        projectIds={projectIds}
        cards={cards}
        running={running}
        lastUpdated={lastUpdated}
        snapshotFingerprint={snapshotFingerprint}
        toolbar={toolbar}
        actions={actions}
        feedback={feedback}
        emptyMessages={emptyMessages}
        pinnedByFingerprint={pinnedByFingerprint}
        emptySelection={emptySelection}
        empty={empty}
        analysisChildren={analysisChildren}
        actionsDisclosure={actionsDisclosure}
        showToolbar={showToolbar}
        synthesis={synthesis}
      />
    );
  }

  return (
    <div className="space-y-4">
      {showToolbar && <IntelligenceStrip {...toolbar} scope={scope} />}

      {projectIds.length === 0 && !running && (emptySelection ?? empty)}

      {projectIds.length > 0 && (
      <div className="space-y-4">
        <InsightSection
          title="Risks"
          icon={<IconAlertTriangle size={16} className="text-warning" />}
          cards={risks}
          emptyText={emptyMessages.risks}
          loading={running}
          actions={actions}
          feedback={feedback}
          pinnedByFingerprint={pinnedByFingerprint}
          actionsDisclosure={actionsDisclosure}
        />
        <InsightSection
          title="Trends"
          icon={<IconTrendingUp size={16} className="text-ink-secondary" />}
          cards={trends}
          emptyText={emptyMessages.trends}
          loading={running}
          actions={actions}
          feedback={feedback}
          pinnedByFingerprint={pinnedByFingerprint}
          actionsDisclosure={actionsDisclosure}
        />
        <InsightSection
          title="Opportunities"
          icon={<IconBulb size={16} className="text-success" />}
          cards={opportunities}
          emptyText={emptyMessages.opportunities}
          loading={running}
          actions={actions}
          feedback={feedback}
          pinnedByFingerprint={pinnedByFingerprint}
          actionsDisclosure={actionsDisclosure}
        />

        <PercentChangeSummaryPanel
          projectIds={projectIds}
          snapshotFingerprint={fingerprint}
        />

        <InsightSection
          title="Deeper analysis"
          icon={<IconChartBar size={16} className="text-brand-500" />}
          cards={analysis}
          emptyText={emptyMessages.analysis}
          loading={running}
          actions={actions}
          feedback={feedback}
          pinnedByFingerprint={pinnedByFingerprint}
          actionsDisclosure={actionsDisclosure}
        >
          {analysisChildren}
        </InsightSection>
      </div>
      )}
    </div>
  );
}
