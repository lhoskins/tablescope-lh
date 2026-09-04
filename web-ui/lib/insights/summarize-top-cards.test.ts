import { describe, expect, it } from "vitest";
import type { InsightCard } from "@/lib/api/home-intelligence";
import { summarizeTopCards } from "./summarize-top-cards";

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

describe("summarizeTopCards", () => {
  it("returns null for an empty list", () => {
    expect(summarizeTopCards([], "risk")).toBeNull();
  });

  it("uses the single card's own title/summary unchanged when there is only one", () => {
    const only = card({ id: "a", title: "Only risk", summary: "The only risk here." });
    const result = summarizeTopCards([only], "risk");
    expect(result).toEqual({
      title: "Only risk",
      summary: "The only risk here.",
      topCard: only,
      consideredCount: 1,
    });
  });

  it("picks the highest-priority card as the lead, not array position 0", () => {
    // Live report: Priority insights picked whichever card was first in an
    // unsorted, cross-project-concatenated array -- not the most impactful.
    const arrayFirstButLowPriority = card({
      id: "first",
      severity: "info",
      title: "Minor note",
      summary: "Low-severity noise.",
    });
    const actuallyMostImpactful = card({
      id: "second",
      severity: "critical",
      title: "Critical delivery risk",
      summary: "The real headline finding.",
    });
    const result = summarizeTopCards(
      [arrayFirstButLowPriority, actuallyMostImpactful],
      "risk",
    );
    expect(result?.topCard.id).toBe("second");
    expect(result?.summary).toContain("The real headline finding.");
  });

  it("names up to two runner-up titles when there are more than one card", () => {
    const top = card({ id: "top", severity: "critical", title: "Top risk" });
    const second = card({ id: "second", severity: "urgent", title: "Second risk" });
    const third = card({ id: "third", severity: "warning", title: "Third risk" });
    const fourth = card({ id: "fourth", severity: "watch", title: "Fourth risk" });
    const result = summarizeTopCards([fourth, third, second, top], "risk");
    expect(result?.title).toBe("4 risks — led by Top risk");
    expect(result?.summary).toContain("Also flagged: Second risk; Third risk.");
    expect(result?.summary).not.toContain("Fourth risk");
  });

  it("considers at most the top 10 cards", () => {
    const cards = Array.from({ length: 20 }, (_, i) =>
      card({ id: `c${i}`, severity: "warning", title: `Risk ${i}` }),
    );
    const result = summarizeTopCards(cards, "risk");
    expect(result?.consideredCount).toBe(10);
  });
});
