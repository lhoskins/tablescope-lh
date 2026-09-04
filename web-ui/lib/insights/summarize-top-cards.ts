import type { InsightCard } from "@/lib/api/home-intelligence";
import { topByPriority } from "./card-priority";

export interface SummarizedInsights {
  /** Headline for the synthesized preview. */
  title: string;
  /** Body text for the synthesized preview. */
  summary: string;
  /** The single highest-priority card behind this summary -- used for
   * navigation ("Review insight" / "Review supporting evidence" link to
   * its own analysis page, since a synthesized summary has no single
   * insightId of its own). */
  topCard: InsightCard;
  /** How many cards (capped at 10) were actually considered. */
  consideredCount: number;
}

/**
 * Rank `cards` by impact (`cardPriority` -- the same severity/confidence/
 * evidence scoring the backend uses to rank cards at generation time),
 * take the top 10, and synthesize one headline + summary representing them.
 *
 * Live report: the Business Insight page's "Priority insights" tiles and
 * Executive Brief were each picking whichever card happened to be first in
 * an unsorted, cross-project-concatenated array -- not the most impactful
 * one, and never a summary of more than one card. This ranks first, then
 * follows the same deterministic-synthesis approach the backend's own
 * `synthesise_cross_project` already uses (cite the real top finding's own
 * title/summary rather than fabricate new prose across many cards), just
 * extended to also name the next couple of runners-up so "top ten,
 * summarized" means something beyond "top one" when there's more than one
 * card to consider.
 */
export function summarizeTopCards(
  cards: InsightCard[],
  noun: string,
): SummarizedInsights | null {
  if (!cards.length) return null;
  const ranked = topByPriority(cards, 10);
  const [top, ...rest] = ranked;

  if (ranked.length === 1) {
    return { title: top.title, summary: top.summary, topCard: top, consideredCount: 1 };
  }

  const others = rest.slice(0, 2);
  const title = `${ranked.length} ${noun}${ranked.length === 1 ? "" : "s"} — led by ${top.title}`;
  const otherNote =
    others.length > 0 ? ` Also flagged: ${others.map((c) => c.title).join("; ")}.` : "";

  return {
    title,
    summary: `${top.summary}${otherNote}`,
    topCard: top,
    consideredCount: ranked.length,
  };
}
