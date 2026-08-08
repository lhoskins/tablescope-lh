import type { InsightCard } from "@/lib/api/home-intelligence";

export interface ClassifiedInsightCards {
  risks: InsightCard[];
  trends: InsightCard[];
  opportunities: InsightCard[];
  analysis: InsightCard[];
}

/**
 * Classify insight cards into the four shared buckets.
 *
 * Uses the same priority rules as the Business Insight feed:
 * 1. Risks: insightType starts with "risk_" OR severity is critical/urgent/warning.
 * 2. Trends: insightType starts with "trend_" and not already a risk.
 * 3. Opportunities: insightType starts with "opportunity_" OR severity is
 *    opportunity/recommendation, and not already a risk or trend.
 * 4. Deeper analysis: everything else.
 *
 * A card can appear in at most one bucket.
 */
export function classifyInsightCards(
  cards: InsightCard[],
): ClassifiedInsightCards {
  const risks = cards.filter(
    (c) =>
      c.insightType.startsWith("risk_") ||
      c.severity === "critical" ||
      c.severity === "urgent" ||
      c.severity === "warning",
  );

  const trends = cards.filter(
    (c) => c.insightType.startsWith("trend_") && !risks.includes(c),
  );

  const opportunities = cards.filter(
    (c) =>
      (c.insightType.startsWith("opportunity_") ||
        c.severity === "opportunity" ||
        c.severity === "recommendation") &&
      !risks.includes(c) &&
      !trends.includes(c),
  );

  const analysis = cards.filter(
    (c) =>
      !risks.includes(c) &&
      !trends.includes(c) &&
      !opportunities.includes(c),
  );

  return { risks, trends, opportunities, analysis };
}
