import type {
  HomePersona,
  InsightCard,
} from "@/lib/api/home-intelligence";
import type { HomeDocumentRow } from "@/lib/ui/use-shell-data";

export const DEFAULT_HOME_PERSONA: HomePersona = "executive";

export const HOME_PERSONAS: Array<{ value: HomePersona; label: string }> = [
  { value: "ceo", label: "CEO" },
  { value: "cfo", label: "CFO" },
  { value: "cio", label: "CIO" },
  { value: "cdo", label: "CDO" },
  { value: "executive", label: "Executive" },
  { value: "it_manager", label: "IT Manager" },
  { value: "it_director", label: "IT Director" },
  { value: "manufacturing_director", label: "Manufacturing Director" },
  { value: "business_analyst", label: "Business Analyst" },
  { value: "engineer", label: "Engineer" },
];

type PersonaProfile = {
  label: string;
  purpose: string;
  keywords: string[];
  metricLabels: [string, string, string, string];
};

const PROFILES: Record<HomePersona, PersonaProfile> = {
  ceo: {
    label: "CEO",
    purpose: "Company performance, material risks, strategic opportunities, and decisions requiring executive attention.",
    keywords: ["revenue", "growth", "forecast", "backlog", "risk", "opportunity", "strategy", "performance", "customer"],
    metricLabels: ["Projects monitored", "Material risks", "Opportunities", "Decisions due"],
  },
  cfo: {
    label: "CFO",
    purpose: "Financial performance, forecast confidence, cost exposure, conversion, and approvals.",
    keywords: ["revenue", "cost", "spend", "budget", "margin", "cash", "backlog", "forecast", "financial"],
    metricLabels: ["Projects monitored", "Financial risks", "Opportunities", "Approvals due"],
  },
  cio: {
    label: "CIO",
    purpose: "Technology reliability, service performance, operational risk, investment, and transformation outcomes.",
    keywords: ["technology", "service", "incident", "sla", "availability", "security", "infrastructure", "capacity", "transformation"],
    metricLabels: ["Projects monitored", "Technology risks", "Opportunities", "Actions due"],
  },
  cdo: {
    label: "CDO",
    purpose: "Data quality, governance, adoption, analytical value, and decisions enabled by trusted information.",
    keywords: ["data", "quality", "governance", "analytics", "source", "lineage", "adoption", "metric", "insight"],
    metricLabels: ["Projects monitored", "Data risks", "Opportunities", "Approvals due"],
  },
  executive: {
    label: "Executive",
    purpose: "Cross-functional performance, material changes, enterprise risks, opportunities, and decisions.",
    keywords: ["performance", "revenue", "risk", "opportunity", "forecast", "backlog", "customer", "sla", "recommendation"],
    metricLabels: ["Projects monitored", "Material risks", "Opportunities", "Decisions due"],
  },
  it_manager: {
    label: "IT Manager",
    purpose: "Team workload, service levels, incidents, queues, and actions requiring daily follow-through.",
    keywords: ["incident", "request", "sla", "resolution", "backlog", "workload", "queue", "service", "support"],
    metricLabels: ["Projects monitored", "Service risks", "Opportunities", "Actions due"],
  },
  it_director: {
    label: "IT Director",
    purpose: "Regional service performance, infrastructure health, capacity, operating risk, and management actions.",
    keywords: ["availability", "incident", "sla", "capacity", "infrastructure", "regional", "security", "service", "reliability"],
    metricLabels: ["Projects monitored", "Operational risks", "Opportunities", "Actions due"],
  },
  manufacturing_director: {
    label: "Manufacturing Director",
    purpose: "Throughput, quality, schedule adherence, downtime, constraints, and plant-level corrective actions.",
    keywords: ["manufacturing", "production", "throughput", "quality", "downtime", "yield", "schedule", "plant", "site"],
    metricLabels: ["Projects monitored", "Plant risks", "Opportunities", "Actions due"],
  },
  business_analyst: {
    label: "Business Analyst",
    purpose: "Evidence, variance, trends, data quality, analytical questions, and findings requiring validation.",
    keywords: ["variance", "trend", "change", "analysis", "metric", "correlation", "forecast", "data", "outlier"],
    metricLabels: ["Projects monitored", "Open findings", "Opportunities", "Analyses due"],
  },
  engineer: {
    label: "Engineer",
    purpose: "System behavior, defects, reliability, technical dependencies, root causes, and engineering work.",
    keywords: ["defect", "failure", "reliability", "root cause", "system", "technical", "performance", "dependency", "repair"],
    metricLabels: ["Projects monitored", "Technical risks", "Opportunities", "Actions due"],
  },
};

const SEVERITY_WEIGHT: Record<string, number> = {
  critical: 80,
  urgent: 70,
  warning: 55,
  opportunity: 45,
  recommendation: 38,
  watch: 32,
  trend: 28,
  informational: 18,
  info: 18,
};

export type HomeDevelopment =
  | {
      kind: "insight";
      id: string;
      projectId: string;
      projectName: string;
      title: string;
      summary: string;
      badge: string;
      href: string;
      occurredAt: string | null;
    }
  | {
      kind: "document";
      id: string;
      projectId: string;
      projectName: string;
      title: string;
      summary: string;
      badge: string;
      href: string;
      occurredAt: string | null;
    };

export function normalizeHomePersona(value: unknown): HomePersona {
  return HOME_PERSONAS.some((option) => option.value === value)
    ? (value as HomePersona)
    : DEFAULT_HOME_PERSONA;
}

export function homePersonaProfile(persona: HomePersona): PersonaProfile {
  return PROFILES[persona];
}

function searchableInsight(card: InsightCard): string {
  return [
    card.title,
    card.summary,
    card.insightType,
    card.projectName,
    card.callout?.text,
    ...(card.sources?.documents ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function keywordScore(text: string, keywords: string[]): number {
  return keywords.reduce(
    (score, keyword) => score + (text.includes(keyword) ? 12 : 0),
    0,
  );
}

export function rankHomeInsights(
  cards: InsightCard[],
  persona: HomePersona,
  focus: string[] = [],
): InsightCard[] {
  const profile = PROFILES[persona];
  const focusTerms = focus.map((term) => term.trim().toLowerCase()).filter(Boolean);
  return [...cards].sort((a, b) => {
    const score = (card: InsightCard) => {
      const text = searchableInsight(card);
      const priority = Math.max(0, Math.min(100, card.priorityScore ?? 0));
      const focusScore = focusTerms.reduce(
        (total, term) => total + (text.includes(term) ? 30 : 0),
        0,
      );
      return (
        (SEVERITY_WEIGHT[card.severity] ?? 20) +
        priority +
        keywordScore(text, profile.keywords) +
        focusScore
      );
    };
    return score(b) - score(a);
  });
}

export function selectPerformanceInsight(cards: InsightCard[]): InsightCard | null {
  return (
    cards.find(
      (card) => card.chart && card.chart.type !== "kpi_grid",
    ) ?? cards.find((card) => card.chart) ?? null
  );
}

function rankDocuments(
  documents: HomeDocumentRow[],
  persona: HomePersona,
  focus: string[],
): HomeDocumentRow[] {
  const profile = PROFILES[persona];
  const focusTerms = focus.map((term) => term.trim().toLowerCase()).filter(Boolean);
  const score = (document: HomeDocumentRow) => {
    const text = [document.name, document.aiSummary, document.projectName]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    const focusScore = focusTerms.reduce(
      (total, term) => total + (text.includes(term) ? 30 : 0),
      0,
    );
    const timestamp = Date.parse(document.updatedAt ?? document.createdAt ?? "") || 0;
    const recency = Math.min(20, Math.max(0, (timestamp - Date.now() + 2_592_000_000) / 129_600_000));
    return keywordScore(text, profile.keywords) + focusScore + recency;
  };
  return [...documents]
    .filter((document) => Boolean(document.aiSummary?.trim()))
    .sort((a, b) => score(b) - score(a));
}

export function buildHomeDevelopments(
  cards: InsightCard[],
  documents: HomeDocumentRow[],
  persona: HomePersona,
  focus: string[] = [],
): HomeDevelopment[] {
  const insights = rankHomeInsights(cards, persona, focus).slice(0, 3).map((card) => ({
    kind: "insight" as const,
    id: card.insightId || card.id,
    projectId: card.projectId,
    projectName: card.projectName,
    title: card.title,
    summary: card.summary,
    badge: card.severity === "opportunity" ? "Opportunity" : card.severity,
    href: `/business-insight/analysis/${encodeURIComponent(card.insightId || card.id)}`,
    occurredAt: card.executedAt || null,
  }));
  const document = rankDocuments(documents, persona, focus)[0];
  const documentDevelopment = document
    ? {
        kind: "document" as const,
        id: String(document.id),
        projectId: String(document.projectId),
        projectName: document.projectName,
        title: document.name,
        summary: document.aiSummary || "AI-indexed project document.",
        badge: "Document",
        href: `/projects/${document.projectId}/documents/${document.id}`,
        occurredAt: document.updatedAt ?? document.createdAt,
      }
    : null;

  if (!documentDevelopment) return insights.slice(0, 4);
  return [insights[0], documentDevelopment, ...insights.slice(1)]
    .filter((item): item is HomeDevelopment => Boolean(item))
    .slice(0, 4);
}
