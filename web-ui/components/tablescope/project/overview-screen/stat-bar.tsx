"use client";

import Link from "next/link";
import {
  IconDatabase,
  IconTable,
  IconFileText,
  IconLayoutDashboard,
  IconSparkles,
} from "@tabler/icons-react";

interface StatItem {
  key: string;
  icon: typeof IconDatabase;
  iconClass: string;
  value: number;
  label: string;
  /** Omitted for stats with no dedicated project page (e.g. AI actions). */
  href?: string;
}

/** One-row project stat strip. Five items only, evenly distributed and
 *  wrapping their own label/value pair — never a horizontal scroller, even
 *  on narrow desktop widths (the icon + stacked text is compact enough to
 *  reflow via flex-wrap instead). Each stat with a corresponding project
 *  page (same routes as the resource tabs above it) links there. */
export function StatBar({
  projectId,
  dataSources,
  tables,
  documents,
  dashboards,
  aiActions,
}: {
  projectId: string;
  dataSources: number;
  tables: number;
  documents: number;
  dashboards: number;
  aiActions: number;
}) {
  const base = `/projects/${projectId}`;

  const items: StatItem[] = [
    {
      key: "sources",
      icon: IconDatabase,
      iconClass: "bg-brand-50 text-brand-700",
      value: dataSources,
      label: "Data sources",
      href: `${base}/data-sources`,
    },
    {
      key: "tables",
      icon: IconTable,
      iconClass: "bg-ai-bg text-ai",
      value: tables,
      label: "Tables",
      href: `${base}/queries`,
    },
    {
      key: "documents",
      icon: IconFileText,
      iconClass: "bg-success-bg text-success",
      value: documents,
      label: "Documents",
      href: `${base}/documents`,
    },
    {
      key: "dashboards",
      icon: IconLayoutDashboard,
      iconClass: "bg-ai-bg text-ai",
      value: dashboards,
      label: "Dashboards",
      href: `${base}/dashboards`,
    },
    {
      key: "ai-actions",
      icon: IconSparkles,
      iconClass: "bg-warning-bg text-warning",
      value: aiActions,
      label: "AI actions",
    },
  ];

  return (
    <section
      aria-label="Project stats"
      className="flex flex-wrap items-center gap-y-3 rounded-lg border border-line-tertiary bg-bg-primary px-5 py-3.5"
    >
      {items.map((item) => {
        const Icon = item.icon;
        const content = (
          <>
            <span
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${item.iconClass}`}
            >
              <Icon size={16} />
            </span>
            <div className="leading-tight">
              <div className="text-[15px] font-semibold tabular-nums text-ink-primary">
                {item.value}
              </div>
              <div className="text-[11px] text-ink-tertiary">{item.label}</div>
            </div>
          </>
        );
        const itemClassName =
          "flex items-center gap-2.5 rounded-md border-line-tertiary px-4 first:pl-0 [&:not(:first-child)]:border-l";

        return item.href ? (
          <Link
            key={item.key}
            href={item.href}
            className={`${itemClassName} hover:bg-bg-secondary`}
          >
            {content}
          </Link>
        ) : (
          <div key={item.key} className={itemClassName}>
            {content}
          </div>
        );
      })}
    </section>
  );
}
