import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type {
  InsightCard,
  InsightDiagnostic,
  ProposedAction,
} from "@/lib/api/home-intelligence";
import { InsightAnalysisStrip } from "./insight-analysis-strip";

const DIAGNOSTIC: InsightDiagnostic = {
  stage: "localise",
  title: "Where it is concentrated",
  question: "Which plant accounts for the shortfall?",
  finding: "Plant B accounts for 62% of the miss.",
  rationale: "A concentrated shortfall is fixable at one site.",
};

const ACTION: ProposedAction = {
  kind: "mitigate",
  headline: "Target Plant B",
  rationale: "Plant B drives 62% of the movement.",
  confidence: "high",
};

function card(overrides: Partial<InsightCard> = {}): InsightCard {
  return {
    id: "card-1",
    insightId: "insight-7",
    projectId: "p1",
    projectName: "Ops",
    projectColor: "#000",
    insightType: "risk_sla",
    severity: "warning",
    title: "On-time delivery below SLA",
    summary: "On-time delivery fell to 88%.",
    chart: null,
    callout: null,
    sources: { tables: [], documents: [] },
    executedAt: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("InsightAnalysisStrip", () => {
  it("renders nothing when the card was never dissected", () => {
    // A card must never advertise an analysis that does not exist.
    const { container } = render(<InsightAnalysisStrip card={card()} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the lead finding and the top proposed action", () => {
    render(
      <InsightAnalysisStrip
        card={card({ diagnostics: [DIAGNOSTIC], proposedActions: [ACTION] })}
      />,
    );
    expect(screen.getByText(/Plant B accounts for 62%/)).toBeTruthy();
    expect(screen.getByText("Target Plant B")).toBeTruthy();
  });

  it("links to the shareable analysis route for this insight", () => {
    render(<InsightAnalysisStrip card={card({ diagnostics: [DIAGNOSTIC] })} />);
    expect(
      screen.getByRole("link", { name: /Full analysis/ }).getAttribute("href"),
    ).toBe("/business-insight/analysis/insight-7");
  });

  it("falls back to the card id when no insightId was issued", () => {
    render(
      <InsightAnalysisStrip
        card={card({ insightId: undefined, diagnostics: [DIAGNOSTIC] })}
      />,
    );
    expect(
      screen.getByRole("link", { name: /Full analysis/ }).getAttribute("href"),
    ).toBe("/business-insight/analysis/card-1");
  });

  it("keeps the card scannable — deeper steps are counted, not listed", () => {
    render(
      <InsightAnalysisStrip
        card={card({
          diagnostics: [DIAGNOSTIC, { ...DIAGNOSTIC, stage: "when" }],
          proposedActions: [ACTION, { ...ACTION, headline: "Watch scrap rate" }],
        })}
      />,
    );
    expect(screen.getByText(/2 diagnostic steps/)).toBeTruthy();
    expect(screen.getByText(/2 proposed actions/)).toBeTruthy();
    expect(screen.queryByText("Watch scrap rate")).toBeNull();
  });

  it("marks a low-confidence action as needing confirmation", () => {
    render(
      <InsightAnalysisStrip
        card={card({
          diagnostics: [DIAGNOSTIC],
          proposedActions: [{ ...ACTION, confidence: "low" }],
        })}
      />,
    );
    expect(screen.getByText(/needs confirmation/)).toBeTruthy();
  });
});
