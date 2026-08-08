import { describe, expect, it } from "vitest";
import type { InsightCard, InsightDiagnostic } from "@/lib/api/home-intelligence";
import { cardContext } from "./insight-ask-box";

const STEP: InsightDiagnostic = {
  stage: "quantify",
  title: "Unusual observations",
  question: "Which fall outside the expected range?",
  rationale: "Separates an outlier from noise.",
  finding: "1 observation outside the expected range.",
  sql: "SELECT month, SUM(RevenueUSD) FROM ledger GROUP BY month ORDER BY month",
  analyticalMethod: { method: "detect_anomalies", executionEngine: "r", status: "ok" },
};

function card(overrides: Partial<InsightCard> = {}): InsightCard {
  return {
    id: "c1",
    insightId: "i1",
    projectId: "7",
    projectName: "Ops",
    projectColor: "#000",
    insightType: "trend_spend",
    severity: "trend",
    title: "Rising material costs",
    summary: "Gross margin fell from 30.9% to 24.4%.",
    chart: null,
    callout: null,
    sources: { tables: ["ledger"], documents: [] },
    executedAt: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("cardContext", () => {
  it("carries the card's own query so a follow-up extends those rows", () => {
    const ctx = cardContext(card({ sql: "SELECT * FROM ledger" }));
    expect(ctx.base_sql).toBe("SELECT * FROM ledger");
  });

  it("falls back to a diagnostic's query when the card has none", () => {
    // Method-driven cards carry their evidence on the step, not the card.
    const ctx = cardContext(card({ diagnostics: [STEP] }));
    expect(ctx.base_sql).toBe(STEP.sql);
  });

  it("sends no query rather than a misleading one when neither has SQL", () => {
    expect(cardContext(card()).base_sql).toBeUndefined();
  });

  it("carries the finding's text so the answer stays on this insight", () => {
    const ctx = cardContext(card());
    expect(ctx.title).toBe("Rising material costs");
    expect(ctx.summary).toContain("30.9%");
    expect(ctx.insight_type).toBe("trend_spend");
    expect(ctx.source_tables).toEqual(["ledger"]);
  });

  it("carries method provenance from the card, else from the first step", () => {
    expect(cardContext(card({ diagnostics: [STEP] })).analytical_method?.method).toBe(
      "detect_anomalies",
    );
    const withOwn = cardContext(
      card({
        analyticalMethod: { method: "period_change", executionEngine: "r", status: "ok" },
        diagnostics: [STEP],
      }),
    );
    expect(withOwn.analytical_method?.method).toBe("period_change");
  });
});
