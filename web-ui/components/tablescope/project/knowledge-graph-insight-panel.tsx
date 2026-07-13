"use client";

import { Fragment, type ReactNode } from "react";
import {
  IconAlertTriangle,
  IconBulb,
  IconFileText,
  IconTable,
  IconChartBar,
  IconLayoutDashboard,
  IconRoute,
  IconTargetArrow,
} from "@tabler/icons-react";
import type {
  KnowledgeGraphInsightCard,
  KnowledgeGraphCardCategory,
} from "@/lib/ui/use-project-data";
import { SEVERITY_META } from "./knowledge-graph-style";

function renderBold(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-ink-primary">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

const CATEGORY_SECTIONS: {
  category: KnowledgeGraphCardCategory;
  heading: string;
}[] = [
  { category: "business_insight", heading: "Knowledge Graph Business Insight" },
  { category: "opportunity", heading: "Knowledge Graph Opportunities" },
  { category: "risk", heading: "Knowledge Graph Risks" },
  { category: "warning", heading: "Knowledge Graph Warnings" },
  { category: "gap", heading: "Knowledge Graph Gaps" },
  { category: "recommendation", heading: "Knowledge Graph Recommendations" },
];

function SourceChips({ card }: { card: KnowledgeGraphInsightCard }) {
  const items: { icon: ReactNode; label: string }[] = [];
  for (const d of card.sourceDocuments.slice(0, 3))
    items.push({ icon: <IconFileText size={12} />, label: d });
  for (const t of card.sourceTables.slice(0, 3))
    items.push({ icon: <IconTable size={12} />, label: t });
  for (const q of card.sourceQueries.slice(0, 2))
    items.push({ icon: <IconChartBar size={12} />, label: q });
  for (const d of card.sourceDashboards.slice(0, 2))
    items.push({ icon: <IconLayoutDashboard size={12} />, label: d });
  for (const k of card.supportedKpis.slice(0, 3))
    items.push({ icon: <IconTargetArrow size={12} />, label: k });
  if (items.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line-tertiary pt-3 text-small text-ink-tertiary">
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          {it.icon} {it.label}
        </span>
      ))}
    </div>
  );
}

function Card({
  card,
  isTracing,
  onTrace,
}: {
  card: KnowledgeGraphInsightCard;
  isTracing: boolean;
  onTrace: (card: KnowledgeGraphInsightCard) => void;
}) {
  const sev = SEVERITY_META[card.severity] ?? SEVERITY_META.info;
  const canTrace = card.traceToEvidence.nodeIds.length > 0;
  return (
    <article
      className={`rounded-lg border border-line-tertiary bg-bg-primary p-4`}
    >
      <header className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 text-h3 text-ink-primary">{card.title}</h3>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-small font-medium ${sev.chip}`}
        >
          {sev.label}
        </span>
      </header>

      {card.businessQuestion && (
        <p className="mt-1 text-small italic text-ink-tertiary">
          {card.businessQuestion}
        </p>
      )}

      <p className="mt-2 text-body text-ink-secondary">
        {renderBold(card.summary)}
      </p>

      {card.businessImpact && (
        <div className="mt-3 flex items-start gap-2 rounded-md bg-warning/10 p-3 text-small text-ink-secondary">
          <IconAlertTriangle size={16} className="mt-0.5 shrink-0 text-warning" />
          <span>{renderBold(card.businessImpact)}</span>
        </div>
      )}

      {card.recommendedAction && (
        <div className="mt-3 flex items-start gap-2 rounded-md bg-success/10 p-3 text-small text-ink-secondary">
          <IconBulb size={16} className="mt-0.5 shrink-0 text-success" />
          <span>{renderBold(card.recommendedAction)}</span>
        </div>
      )}

      <SourceChips card={card} />

      <footer className="mt-3 flex items-center justify-between gap-2">
        <span className="text-small text-ink-tertiary">
          Confidence {Math.round((card.confidence || 0) * 100)}%
        </span>
        {canTrace && (
          <button
            type="button"
            onClick={() => onTrace(card)}
            className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-small font-medium transition-colors ${
              isTracing
                ? "border-brand bg-brand/10 text-brand"
                : "border-line-tertiary text-ink-secondary hover:border-line-secondary hover:bg-bg-tertiary"
            }`}
          >
            <IconRoute size={14} /> {isTracing ? "Tracing" : "Trace to Evidence"}
          </button>
        )}
      </footer>
    </article>
  );
}

interface PanelProps {
  title: string;
  subtitle?: string;
  cards: KnowledgeGraphInsightCard[];
  tracingCardId: string | null;
  onTrace: (card: KnowledgeGraphInsightCard) => void;
  onClose?: () => void;
}

export function KnowledgeGraphInsightPanel({
  title,
  subtitle,
  cards,
  tracingCardId,
  onTrace,
}: PanelProps) {
  const byCategory = new Map<KnowledgeGraphCardCategory, KnowledgeGraphInsightCard[]>();
  for (const c of cards) {
    const arr = byCategory.get(c.category) ?? [];
    arr.push(c);
    byCategory.set(c.category, arr);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line-tertiary px-4 py-3">
        <h2 className="text-h3 text-ink-primary">{title}</h2>
        {subtitle && (
          <p className="mt-0.5 text-small text-ink-tertiary">{subtitle}</p>
        )}
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
        {cards.length === 0 && (
          <p className="text-small text-ink-tertiary">
            No business insights available for this node yet. Click Refresh to
            rebuild the Knowledge Graph or lower the confidence filter.
          </p>
        )}
        {CATEGORY_SECTIONS.map(({ category, heading }) => {
          const sectionCards = byCategory.get(category) ?? [];
          if (sectionCards.length === 0) return null;
          return (
            <section key={category}>
              <h4 className="mb-2 text-small font-semibold uppercase tracking-wide text-ink-tertiary">
                {heading}
              </h4>
              <div className="space-y-3">
                {sectionCards.map((card) => (
                  <Card
                    key={card.id}
                    card={card}
                    isTracing={tracingCardId === card.id}
                    onTrace={onTrace}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
