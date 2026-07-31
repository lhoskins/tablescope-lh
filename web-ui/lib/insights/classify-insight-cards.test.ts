import { describe, expect, it } from "vitest";
import { classifyInsightCards } from "./classify-insight-cards";
import type { InsightCard } from "@/lib/api/home-intelligence";

const BASE: InsightCard = {
  id: "c1",
  projectId: "1",
  projectName: "P",
  projectColor: "#000",
  insightType: "risk_sla",
  severity: "critical",
  title: "Card",
  summary: "Summary",
  chart: null,
  callout: null,
  sources: { tables: [], documents: [] },
  executedAt: "",
};

function make(partial: Partial<InsightCard>): InsightCard {
  return { ...BASE, ...partial } as InsightCard;
}

describe("classifyInsightCards", () => {
  it("classifies risk insight types", () => {
    const cards = [make({ insightType: "risk_sla", severity: "informational" })];
    const result = classifyInsightCards(cards);
    expect(result.risks).toHaveLength(1);
    expect(result.trends).toHaveLength(0);
    expect(result.opportunities).toHaveLength(0);
    expect(result.analysis).toHaveLength(0);
  });

  it("classifies by risk severity when type is not risk", () => {
    const cards = [make({ insightType: "future_type", severity: "critical" })];
    const result = classifyInsightCards(cards);
    expect(result.risks).toHaveLength(1);
  });

  it("classifies trend insight types", () => {
    const cards = [make({ insightType: "trend_spend", severity: "watch" })];
    const result = classifyInsightCards(cards);
    expect(result.risks).toHaveLength(0);
    expect(result.trends).toHaveLength(1);
  });

  it("does not put a card in both risk and trend", () => {
    const cards = [
      make({ insightType: "trend_spend", severity: "critical" }),
    ];
    const result = classifyInsightCards(cards);
    expect(result.risks).toHaveLength(1);
    expect(result.trends).toHaveLength(0);
  });

  it("classifies opportunity insight types", () => {
    const cards = [
      make({ insightType: "opportunity_supplier", severity: "informational" }),
    ];
    const result = classifyInsightCards(cards);
    expect(result.opportunities).toHaveLength(1);
  });

  it("classifies by opportunity severity", () => {
    const cards = [make({ insightType: "shape_bar", severity: "opportunity" })];
    const result = classifyInsightCards(cards);
    expect(result.opportunities).toHaveLength(1);
  });

  it("does not duplicate membership across buckets", () => {
    const cards = [
      make({ id: "r", insightType: "risk_sla", severity: "critical" }),
      make({ id: "t", insightType: "trend_spend", severity: "watch" }),
      make({ id: "o", insightType: "opportunity_supplier", severity: "recommendation" }),
      make({ id: "a", insightType: "shape_scatter", severity: "informational" }),
    ];
    const result = classifyInsightCards(cards);
    expect(result.risks.map((c) => c.id)).toEqual(["r"]);
    expect(result.trends.map((c) => c.id)).toEqual(["t"]);
    expect(result.opportunities.map((c) => c.id)).toEqual(["o"]);
    expect(result.analysis.map((c) => c.id)).toEqual(["a"]);

    const all = [
      ...result.risks,
      ...result.trends,
      ...result.opportunities,
      ...result.analysis,
    ];
    expect(all).toHaveLength(cards.length);
    const ids = all.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("falls unknown types into deeper analysis", () => {
    const cards = [make({ insightType: "shape_scatter", severity: "informational" })];
    const result = classifyInsightCards(cards);
    expect(result.analysis).toHaveLength(1);
  });
});
