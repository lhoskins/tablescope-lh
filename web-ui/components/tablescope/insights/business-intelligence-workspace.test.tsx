import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { InsightCard } from "@/lib/api/home-intelligence";

import { BusinessIntelligenceWorkspace } from "./business-intelligence-workspace";

const mockRenderBold = vi.fn((text: string) => text);

vi.mock("@/components/tablescope/home/intelligence-card", () => ({
  renderBold: (text: string) => mockRenderBold(text),
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
      />,
    );

    expect(screen.getAllByText("risk-1 title").length).toBeGreaterThan(0);
    expect(screen.getAllByText("risk-1 summary").length).toBeGreaterThan(0);
    expect(screen.queryByText(/AI analyzed/i)).toBeNull();
    expect(screen.getByLabelText("1 risks")).toBeTruthy();
    expect(screen.getByLabelText("1 trends")).toBeTruthy();
    expect(screen.getByLabelText("1 opportunities")).toBeTruthy();
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

  it("renders Priority insights card summaries through renderBold, not raw text", () => {
    // Live report: "Open actions rose from **16.0** in **2026-02**..."
    // rendered with literal asterisks in the Overview tab's Priority
    // insights cards -- this custom preview block builds its own markup
    // (it doesn't reuse <IntelligenceCard>, which already calls renderBold
    // for its own summary/title/callout) and had simply omitted the call.
    // A risk card always wins the Executive Brief slot (executiveBriefCard
    // picks risks[0] first), so asserting against the risk's own summary
    // wouldn't discriminate between "the Priority insights block calls
    // renderBold" and "only the Executive Brief happens to call it" -- a
    // trend card's summary can only reach renderBold via the Priority
    // insights block in this scenario.
    mockRenderBold.mockClear();
    render(
      <BusinessIntelligenceWorkspace
        projectIds={[1]}
        cards={[
          card("risk-1", "risk_delivery", "urgent"),
          card("trend-1", "trend_revenue", "trend"),
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

    expect(mockRenderBold).toHaveBeenCalledWith("trend-1 summary");
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

  it("Priority insights tile is led by the most impactful card in its category, not array position 0", () => {
    // Live report: the Risk/Trend/Opportunity tiles picked whichever card
    // was first in the array -- not the most severe/impactful one.
    render(
      <BusinessIntelligenceWorkspace
        projectIds={[1]}
        cards={[
          card("risk-low", "risk_delivery", "warning"),
          card("risk-high", "risk_delivery", "critical"),
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

    // Synthesized title: "2 risks — led by risk-high title". Appears in
    // both the Priority insights tile and the Executive Brief here (this
    // scenario has only risk cards, so risk-high also wins the executive
    // brief) -- assert it renders at all, and never the array-first card.
    expect(screen.getAllByText(/led by risk-high title/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/led by risk-low title/)).toBeNull();
    // Severity badge reflects the actual lead card (critical), not the
    // array-first card (warning).
    expect(screen.getByText("Risk · critical")).toBeInTheDocument();
  });

  it("shows a neutral loading state instead of 'No pressing matters' during the initial fetch", () => {
    // Live report: a static "No Pressing" message showed before the
    // Executive Brief had even finished its first load -- `running` (an
    // active AI refresh) was false, but so was there any data yet, and the
    // two were being treated as the same "nothing to show" case.
    render(
      <BusinessIntelligenceWorkspace
        projectIds={[1]}
        cards={[]}
        running={false}
        initialLoading={true}
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
        showToolbar={false}
      />,
    );

    expect(screen.getByText(/Loading the executive briefing/)).toBeInTheDocument();
    expect(
      screen.queryByText(/No pressing matters require executive attention/),
    ).toBeNull();
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
