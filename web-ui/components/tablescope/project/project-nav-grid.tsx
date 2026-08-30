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
      className="flex flex-wrap items-stretch gap-[7px] px-5 py-2.5"
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
              "flex min-w-[68px] shrink-0 flex-col items-center justify-center gap-[3px] rounded-lg border px-2.5 py-2 text-center text-[11px] font-medium transition-colors",
              active
                ? "border-brand-500 bg-brand-50 font-semibold text-brand-500"
                : "border-line-secondary bg-bg-primary text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
            )}
          >
            <Icon
              size={16}
              stroke={1.8}
              className={cn("shrink-0", active ? "opacity-100" : "opacity-70")}
            />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
