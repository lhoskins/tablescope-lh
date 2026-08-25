import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { InsightCard } from "@/lib/api/home-intelligence";

import { BusinessIntelligenceWorkspace } from "./business-intelligence-workspace";

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  IntelligenceCard: ({
    card,
    presentation,
  }: {
    card: InsightCard;
    presentation?: string;
  }) => (
    <div data-testid="insight-card" data-presentation={presentation}>
      {card.title}
    </div>
  ),
}));

vi.mock("@/components/tablescope/home/percent-change-summary-panel", () => ({
  PercentChangeSummaryPanel: ({ presentation }: { presentation?: string }) => (
    <div data-testid="change-summary" data-presentation={presentation} />
  ),
}));

vi.mock("@/lib/insights/return-target", () => ({
  insightAnchorId: (id: string) => `insight-${id}`,
  useReturnTarget: () => null,
}));

function card(
  id: string,
  insightType: string,
  severity: InsightCard["severity"],
): InsightCard {
  return {
    id,
    insightId: id,
    projectId: "1",
    projectName: "Project A",
    projectColor: "#2563eb",
    insightType,
    severity,
    title: `${id} title`,
    summary: `${id} summary`,
    chart: null,
    callout: null,
    sources: { tables: [], documents: [] },
    executedAt: "2026-08-25T00:00:00Z",
  };
}

describe("BusinessIntelligenceWorkspace", () => {
  it("switches tabs and gives cards the executive presentation", () => {
    render(
      <BusinessIntelligenceWorkspace
        projectIds={[1]}
        cards={[
          card("risk-1", "risk_delivery", "urgent"),
          card("trend-1", "trend_revenue", "trend"),
          card("opportunity-1", "opportunity_capacity", "opportunity"),
        ]}
        running={false}
        lastUpdated={new Date("2026-08-25T00:00:00Z")}
        toolbar={{
          running: false,
          lastUpdatedLabel: null,
          onRefresh: vi.fn(),
          granularity: 50,
          onGranularityChange: vi.fn(),
          availableProjects: [],
          selectedProjectIds: new Set<string>(),
          onToggleProject: vi.fn(),
          onSelectAll: vi.fn(),
          onClear: vi.fn(),
        }}
        actions={{}}
        feedback={{ feedbackById: {}, savingFeedback: false }}
        emptyMessages={{
          risks: "No risks",
          trends: "No trends",
          opportunities: "No opportunities",
          analysis: "No analysis",
        }}
        showToolbar={false}
        synthesis={{
          headline: "Executive headline",
          body: "Executive body",
          projectIds: ["1"],
        }}
      />,
    );

    expect(screen.getByText("Executive headline")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: /Risks/ }));
    expect(document.getElementById("business-insight-panel-risks")).toBeTruthy();
    screen.getAllByTestId("insight-card").forEach((element) => {
      expect(element.getAttribute("data-presentation")).toBe("executive");
    });

    fireEvent.click(screen.getByRole("tab", { name: /Change summary/ }));
    expect(screen.getByTestId("change-summary").getAttribute("data-presentation"))
      .toBe("executive");
    expect(screen.queryByTestId("insight-card")).toBeNull();
  });

  it("only shows the Deeper analysis tab when there is analysis-type content", () => {
    const { rerender } = render(
      <BusinessIntelligenceWorkspace
        projectIds={[1]}
        cards={[card("risk-1", "risk_delivery", "urgent")]}
        running={false}
        lastUpdated={new Date("2026-08-25T00:00:00Z")}
        toolbar={{
          running: false,
          lastUpdatedLabel: null,
          onRefresh: vi.fn(),
          granularity: 50,
          onGranularityChange: vi.fn(),
          availableProjects: [],
          selectedProjectIds: new Set<string>(),
          onToggleProject: vi.fn(),
          onSelectAll: vi.fn(),
          onClear: vi.fn(),
        }}
        actions={{}}
        feedback={{ feedbackById: {}, savingFeedback: false }}
        emptyMessages={{
          risks: "No risks",
          trends: "No trends",
          opportunities: "No opportunities",
          analysis: "No analysis",
        }}
        showToolbar={false}
      />,
    );
    expect(screen.queryByRole("tab", { name: /Deeper analysis/ })).toBeNull();

    rerender(
      <BusinessIntelligenceWorkspace
        projectIds={[1]}
        cards={[
          card("risk-1", "risk_delivery", "urgent"),
          card("analysis-1", "documentation", "info"),
        ]}
        running={false}
        lastUpdated={new Date("2026-08-25T00:00:00Z")}
        toolbar={{
          running: false,
          lastUpdatedLabel: null,
          onRefresh: vi.fn(),
          granularity: 50,
          onGranularityChange: vi.fn(),
          availableProjects: [],
          selectedProjectIds: new Set<string>(),
          onToggleProject: vi.fn(),
          onSelectAll: vi.fn(),
          onClear: vi.fn(),
        }}
        actions={{}}
        feedback={{ feedbackById: {}, savingFeedback: false }}
        emptyMessages={{
          risks: "No risks",
          trends: "No trends",
          opportunities: "No opportunities",
          analysis: "No analysis",
        }}
        showToolbar={false}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: /Deeper analysis/ }));
    expect(document.getElementById("business-insight-panel-analysis")).toBeTruthy();
    expect(screen.getByText("analysis-1 title")).toBeTruthy();
  });

  it("renders the passed header beside the toolbar", () => {
    render(
      <BusinessIntelligenceWorkspace
        projectIds={[1]}
        cards={[]}
        running={false}
        lastUpdated={null}
        toolbar={{
          running: false,
          lastUpdatedLabel: null,
          onRefresh: vi.fn(),
          granularity: 50,
          onGranularityChange: vi.fn(),
          availableProjects: [],
          selectedProjectIds: new Set<string>(),
          onToggleProject: vi.fn(),
          onSelectAll: vi.fn(),
          onClear: vi.fn(),
        }}
        actions={{}}
        feedback={{ feedbackById: {}, savingFeedback: false }}
        emptyMessages={{
          risks: "No risks",
          trends: "No trends",
          opportunities: "No opportunities",
          analysis: "No analysis",
        }}
        header={<h1>Business Insights</h1>}
      />,
    );
    expect(screen.getByRole("heading", { name: "Business Insights" })).toBeTruthy();
  });
});
