import type { InsightCard, InsightSeverity } from "@/lib/api/home-intelligence";

/**
 * TypeScript port of the backend's `card_ranking._card_priority`
 * (platform-api/app/services/home_intelligence/card_ranking.py), used there
 * to rank cards server-side at generation time and referenced by
 * `synthesise_cross_project`'s own docstring as "the same severity-first
 * ranking used for per-project card ranking". Kept in lockstep with that
 * function's weights intentionally, rather than inventing a second scoring
 * model -- every InsightCard already carries the fields it needs
 * (severity/confidenceScore/priorityScore/chart/kpiReferences/
 * referenceDocuments/relationshipMetadata), so this only needs to combine
 * them the same way, client-side, for surfaces that receive cards already
 * concatenated across projects (and therefore not globally re-ranked).
 */
const SEVERITY_RANK: Record<string, number> = {
  critical: 6,
  urgent: 5,
  warning: 4,
  watch: 3,
  opportunity: 3,
  info: 1,
};

function severityRank(severity: InsightSeverity | string | undefined): number {
  return SEVERITY_RANK[severity ?? "info"] ?? 1;
}

export function cardPriority(card: InsightCard): number {
  const explicit = card.priorityScore;
  if (typeof explicit === "number" && explicit > 0) return explicit;

  let score = severityRank(card.severity) * 10;
  const conf = card.confidenceScore;
  score += (typeof conf === "number" ? conf : 0.5) * 3;
  if (card.chart) score += 1;
  if ((card.kpiReferences?.length ?? 0) > 0 || (card.referenceDocuments?.length ?? 0) > 0) {
    score += 2;
  }
  if (card.relationshipMetadata) score += 2.5;
  return score;
}

/** Highest-priority cards first, most impactful/beneficial by the same
 * scoring the backend uses to rank cards at generation time. */
export function rankByPriority(cards: InsightCard[]): InsightCard[] {
  return [...cards].sort((a, b) => cardPriority(b) - cardPriority(a));
}

/** Top `limit` cards by priority (default 10 -- "top ten most impactful"). */
export function topByPriority(cards: InsightCard[], limit = 10): InsightCard[] {
  return rankByPriority(cards).slice(0, limit);
}
