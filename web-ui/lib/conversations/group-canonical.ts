import type { ConversationSummary } from "@/lib/api/conversational-analytics";
import type { ProjectSummary } from "@/lib/ui/types";

/**
 * Group canonical Insight threads so the AI Assistant sidebar shows one durable
 * Business Insights row and one Project Insights row per project. Manual chats
 * remain individual rows. When multiple rows share a canonical key (for
 * example before a data migration fully deduplicates them), the most recently
 * updated row is used as the representative.
 */
export function groupConversationSummaries(
  conversations: ConversationSummary[],
  projects: ProjectSummary[] | undefined,
): ConversationSummary[] {
  const groups = new Map<string, ConversationSummary[]>();
  for (const c of conversations) {
    const key = c.canonical_key ?? `manual:${c.id}`;
    const existing = groups.get(key);
    if (existing) {
      existing.push(c);
    } else {
      groups.set(key, [c]);
    }
  }

  return Array.from(groups.values()).map((items) => {
    const representative = items.reduce((latest, current) =>
      current.updated_at > latest.updated_at ? current : latest,
    );

    if (representative.canonical_key === "business_insights") {
      return { ...representative, title: "Business Insights" };
    }

    if (representative.canonical_key?.startsWith("project_insights:")) {
      const projectId = Number(representative.canonical_key.split(":")[1]);
      const projectName =
        projects?.find((p) => Number(p.id) === projectId)?.name ?? "Project";
      return {
        ...representative,
        title: `Project Insights — ${projectName}`,
      };
    }

    return representative;
  });
}
