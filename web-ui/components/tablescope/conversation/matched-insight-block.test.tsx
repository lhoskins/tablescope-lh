import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MatchedInsightBlock } from "./matched-insight-block";
import type { MatchedInsight } from "@/lib/api/conversational-analytics";

vi.mock("@/components/dashboard/WidgetRenderer", () => ({
  WidgetRenderer: () => <div data-testid="widget" />,
}));

const baseMatch: MatchedInsight = {
  insightId: "mat-cost-001",
  projectId: 7,
  projectName: "Manufacturing",
  title: "Material cost on the rise",
  summary: "Weekly material cost has increased steadily since January 2026.",
  chart: {
    type: "line",
    data: { rows: [{ period: "2026-01", value: 100 }] },
  } as MatchedInsight["chart"],
  severity: "warning",
};

describe("MatchedInsightBlock", () => {
  it("renders the matched card's title, project, and a breadcrumb to the full analysis", () => {
    render(<MatchedInsightBlock match={baseMatch} />);

    expect(screen.getByText("Material cost on the rise")).toBeInTheDocument();
    expect(screen.getByText("Manufacturing")).toBeInTheDocument();

    const link = screen.getByRole("link", { name: /explore full analysis/i });
    expect(link).toHaveAttribute(
      "href",
      "/business-insight/analysis/mat-cost-001",
    );
  });

  it("renders the real chart when the matched card has one", () => {
    render(<MatchedInsightBlock match={baseMatch} />);
    expect(screen.getByTestId("widget")).toBeInTheDocument();
  });

  it("does not render a chart block when the matched card has none", () => {
    render(<MatchedInsightBlock match={{ ...baseMatch, chart: null }} />);
    expect(screen.queryByTestId("widget")).not.toBeInTheDocument();
  });
});
