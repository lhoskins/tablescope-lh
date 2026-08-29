"use client";

import Link from "next/link";
import { cn } from "@/lib/cn";
import { projectGridItems } from "@/components/tablescope/nav";
import type { NavKey } from "@/lib/ui/types";

/**
 * The persistent project nav row (see `docs/ux-workspace-redesign-gap-analysis.md`
 * §3): every project page's top-level sections — Overview, Workspace,
 * Tables, Documents, Dashboards, Data Sources, Project Insights, Project
 * Actions, Reference, Scopes, Knowledge Graph, Chats — as one row of
 * buttons. Replaces the old sidebar "Project" link group and the old
 * `ProjectResourceTabs` strip, which is what lets the sidebar stay locked
 * to the project asset tree instead of switching per page.
 */
export function ProjectNavGrid({
  projectId,
  activeNav,
}: {
  projectId: string;
  activeNav: NavKey;
}) {
  const items = projectGridItems(projectId);

  return (
    <nav
      aria-label="Project sections"
      className="flex items-center gap-1 overflow-x-auto px-5 py-2"
    >
      {items.map((item) => {
        const Icon = item.icon;
        const active = item.key === activeNav;
        return (
          <Link
            key={item.key}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] font-medium transition-colors",
              active
                ? "bg-brand-50 text-brand-700"
                : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
            )}
          >
            <Icon size={14} stroke={1.8} className="shrink-0" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
