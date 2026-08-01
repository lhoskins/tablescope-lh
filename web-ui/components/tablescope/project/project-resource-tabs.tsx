"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

interface Tab {
  label: string;
  href: string;
}

export function ProjectResourceTabs({ projectId }: { projectId: string }) {
  const pathname = usePathname() ?? "";
  const base = `/projects/${projectId}`;

  const tabs: Tab[] = [
    { label: "Overview", href: base },
    { label: "Data Sources", href: `${base}/data-sources` },
    { label: "Tables", href: `${base}/queries` },
    { label: "Documents", href: `${base}/documents` },
    { label: "Dashboards", href: `${base}/dashboards` },
  ];

  const isActive = (tab: Tab) => {
    if (tab.href === base) {
      const segments = pathname.split("/").filter(Boolean);
      return segments.length === 2 && segments[0] === "projects" && segments[1] === projectId;
    }
    return pathname === tab.href || pathname.startsWith(`${tab.href}/`);
  };

  return (
    <nav
      aria-label="Project resources"
      className="flex items-center gap-1 overflow-x-auto px-5 py-2"
    >
      {tabs.map((tab) => {
        const active = isActive(tab);
        return (
          <Link
            key={tab.label}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              // Font weight is identical in both states so switching tabs never
              // reflows the row; the underline carries the active signal.
              "relative flex shrink-0 items-center whitespace-nowrap rounded-md px-3 py-2 text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
              active
                ? "text-ink-primary"
                : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
            )}
          >
            {tab.label}
            {active && (
              <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-brand-500" />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
