import { describe, expect, it } from "vitest";
import type { InsightCard } from "@/lib/api/home-intelligence";
import { cardPriority, rankByPriority, topByPriority } from "./card-priority";

function card(overrides: Partial<InsightCard> = {}): InsightCard {
  return {
    id: overrides.id ?? "c1",
    insightId: overrides.insightId ?? overrides.id ?? "c1",
    projectId: "1",
    projectName: "Project A",
    projectColor: "#2563eb",
    insightType: "risk_delivery",
    severity: "warning",
    title: "Title",
    summary: "Summary",
    chart: null,
    callout: null,
    sources: { tables: [], documents: [] },
    executedAt: "2026-08-25T00:00:00Z",
    ...overrides,
  };
}

describe("cardPriority", () => {
  it("ranks a critical card above a warning card", () => {
    const critical = card({ id: "a", severity: "critical" });
    const warning = card({ id: "b", severity: "warning" });
    expect(cardPriority(critical)).toBeGreaterThan(cardPriority(warning));
  });

  it("an explicit positive priorityScore overrides the derived score", () => {
    const explicit = card({ id: "a", severity: "info", priorityScore: 99 });
    expect(cardPriority(explicit)).toBe(99);
  });

  it("a zero or negative priorityScore falls back to the derived score, not 0", () => {
    const zero = card({ id: "a", severity: "critical", priorityScore: 0 });
    expect(cardPriority(zero)).toBeGreaterThan(0);
  });

  it("confidence, chart presence, references, and relationship metadata all add weight", () => {
    const bare = card({ id: "a" });
    const enriched = card({
      id: "b",
      confidenceScore: 1,
      chart: { type: "line", data: { rows: [] } },
      kpiReferences: ["kpi-1"],
      relationshipMetadata: { leftTable: "a", rightTable: "b" },
    });
    expect(cardPriority(enriched)).toBeGreaterThan(cardPriority(bare));
  });
});

describe("rankByPriority / topByPriority", () => {
  it("sorts highest priority first", () => {
    const low = card({ id: "low", severity: "info" });
    const high = card({ id: "high", severity: "critical" });
    const mid = card({ id: "mid", severity: "warning" });
    expect(rankByPriority([low, high, mid]).map((c) => c.id)).toEqual([
      "high",
      "mid",
      "low",
    ]);
  });

  it("caps the result at the requested limit", () => {
    const cards = Array.from({ length: 15 }, (_, i) => card({ id: `c${i}` }));
    expect(topByPriority(cards, 10)).toHaveLength(10);
  });

  it("does not mutate the input array", () => {
    const low = card({ id: "low", severity: "info" });
    const high = card({ id: "high", severity: "critical" });
    const input = [low, high];
    rankByPriority(input);
    expect(input).toEqual([low, high]);
  });
});
