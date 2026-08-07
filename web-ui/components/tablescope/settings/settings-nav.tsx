"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  IconBuilding,
  IconPhoto,
  IconBook,
  IconBuildingBank,
  IconShieldLock,
  IconLock,
  IconFolders,
  IconMathFunction,
  IconBrain,
  IconUsers,
  IconServer,
  IconRobot,
  IconShieldCheck,
  IconHistory,
  IconDatabaseShare,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import type { CurrentUser } from "@/lib/ui/types";
import {
  canManageDataSourceAssignments,
  canViewProjectIntelligence,
  isPlatformAdmin,
} from "@/lib/ui/permissions";
import { projectIntelligenceNavItems } from "@/components/tablescope/nav";
import { useProjectIntelligenceSelection } from "./use-project-intelligence-selection";

export interface SettingsNavItem {
  key: string;
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  section: string;
  visible: () => boolean;
}

const REVIEW_PERMISSION = "insight_feedback.review";

function isInsightReviewer(user?: CurrentUser): boolean {
  if (!user) return false;
  if (user.permissions?.includes(REVIEW_PERMISSION)) return true;
  return ["admin", "tenant_admin", "root_admin"].includes(user.rawRole ?? "");
}

function isAdmin(user?: CurrentUser): boolean {
  if (!user) return false;
  return (
    ["admin", "tenant_admin", "root_admin"].includes(user.rawRole ?? "") ||
    Boolean(user.isSuperAdmin)
  );
}

function projectIntelligenceSection(
  user: CurrentUser | undefined,
  selectedProjectId: string | null,
): SettingsNavItem[] {
  if (!canViewProjectIntelligence(user)) return [];

  const base = "/admin/settings/project-intelligence";
  if (selectedProjectId) {
    return projectIntelligenceNavItems(selectedProjectId).map((item) => ({
      key: `project-intelligence-${item.key}`,
      label: item.label,
      href: item.href,
      icon: item.icon,
      section: "Project Intelligence",
      visible: () => true,
    }));
  }

  const fallbackItems = [
    { key: "graph-lifecycle", label: "Graph Lifecycle", icon: IconHistory },
    { key: "metadata-catalog", label: "Metadata Catalog", icon: IconBook },
    {
      key: "reference-library",
      label: "Project Reference Library",
      icon: IconBook,
    },
    { key: "audit-log", label: "Audit Log", icon: IconHistory },
  ];

  return fallbackItems.map((item) => ({
    key: `project-intelligence-${item.key}`,
    label: item.label,
    href: base,
    icon: item.icon,
    section: "Project Intelligence",
    visible: () => true,
  }));
}

export function useSettingsNavItems(user?: CurrentUser): {
  sections: { heading: string; items: SettingsNavItem[] }[];
} {
  const { selectedProjectId } = useProjectIntelligenceSelection();

  const items: SettingsNavItem[] = [
    {
      key: "tenant",
      label: "My Tenant",
      href: "/admin/settings/tenant",
      icon: IconBuilding,
      section: "Workspace",
      visible: () => true,
    },
    {
      key: "company",
      label: "Company",
      href: "/admin/settings/company",
      icon: IconPhoto,
      section: "Workspace",
      visible: () => isAdmin(user),
    },
    {
      key: "reference-library",
      label: "Reference Library",
      href: "/admin/settings/reference-library",
      icon: IconBook,
      section: "Knowledge",
      visible: () => isAdmin(user),
    },
    {
      key: "company-library",
      label: "Company Library",
      href: "/admin/settings/company-library",
      icon: IconBuildingBank,
      section: "Knowledge",
      visible: () => isAdmin(user),
    },
    {
      key: "security",
      label: "Two-factor authentication",
      href: "/admin/settings/security",
      icon: IconShieldLock,
      section: "Security",
      visible: () => isAdmin(user),
    },
    {
      key: "allowed-domains",
      label: "Allowed Domains",
      href: "/admin/settings/allowed-domains",
      icon: IconLock,
      section: "Security",
      visible: () => isAdmin(user),
    },
    {
      key: "enterprise-authentication",
      label: "Enterprise Authentication",
      href: "/admin/settings/enterprise-authentication",
      icon: IconShieldCheck,
      section: "Security",
      visible: () => isAdmin(user),
    },
    {
      key: "repositories",
      label: "Repositories",
      href: "/admin/settings/repositories",
      icon: IconFolders,
      section: "Integrations",
      visible: () => isAdmin(user),
    },
    {
      key: "data-source-assignments",
      label: "Data Source Assignments",
      href: "/admin/settings/data-source-assignments",
      icon: IconDatabaseShare,
      section: "Integrations",
      visible: () => canManageDataSourceAssignments(user),
    },
    {
      key: "analytical-methods",
      label: "Analytical Methods",
      href: "/admin/settings/analytical-methods",
      icon: IconMathFunction,
      section: "Intelligence",
      visible: () => isAdmin(user),
    },
    {
      key: "ai-governance",
      label: "AI Governance",
      href: "/admin/settings/ai-governance",
      icon: IconBrain,
      section: "Intelligence",
      visible: () => isAdmin(user),
    },
    {
      key: "insight-feedback-review",
      label: "Insight Review",
      href: "/admin/settings/insight-feedback",
      icon: IconShieldCheck,
      section: "Intelligence",
      visible: () => isAdmin(user) || isInsightReviewer(user),
    },
    ...projectIntelligenceSection(user, selectedProjectId),
    {
      key: "platform-tenants",
      label: "Tenants",
      href: "/admin/settings/platform/tenants",
      icon: IconServer,
      section: "Platform Administration",
      visible: () => isPlatformAdmin(user),
    },
    {
      key: "admin-users",
      label: "Users",
      href: "/admin/users",
      icon: IconUsers,
      section: "Platform Administration",
      visible: () => isPlatformAdmin(user),
    },
    {
      key: "llm-framework",
      label: "LLM Framework",
      href: "/admin/settings/llm-framework",
      icon: IconRobot,
      section: "Platform Administration",
      visible: () => isPlatformAdmin(user),
    },
  ].filter((i) => i.visible());

  const sectionsMap = new Map<string, SettingsNavItem[]>();
  for (const item of items) {
    const list = sectionsMap.get(item.section) ?? [];
    list.push(item);
    sectionsMap.set(item.section, list);
  }

  return {
    sections: Array.from(sectionsMap.entries()).map(([heading, items]) => ({
      heading,
      items,
    })),
  };
}

interface SettingsNavProps {
  user?: CurrentUser;
}

function isActive(pathname: string, href: string): boolean {
  // The Project Intelligence landing route is shared by the four subsection
  // links when no project has been selected yet; don't highlight all of them.
  if (href === "/admin/settings/project-intelligence") return false;
  if (pathname === href) return true;
  if (href.startsWith("/admin/settings/project-intelligence/")) {
    return pathname.startsWith(href);
  }
  return pathname.startsWith(`${href}/`);
}

export function SettingsNav({ user }: SettingsNavProps) {
  const pathname = usePathname();
  const { sections } = useSettingsNavItems(user);

  return (
    <div className="space-y-6">
      <label className="block md:hidden">
        <span className="sr-only">Settings section</span>
        <select
          className="w-full rounded-md border border-line-secondary bg-bg-primary px-3 py-2 text-sm text-ink-primary focus:border-brand-500 focus:outline-none"
          value={pathname ?? ""}
          onChange={(e) => {
            window.location.href = e.target.value;
          }}
        >
          {sections.map((s) => (
            <optgroup key={s.heading} label={s.heading}>
              {s.items.map((item) => (
                <option key={item.key} value={item.href}>
                  {item.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>

      <nav className="hidden md:block" aria-label="Settings sections">
        {sections.map((section) => (
          <div key={section.heading} className="mb-5">
            <div className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">
              {section.heading}
            </div>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const active = isActive(pathname ?? "", item.href);
                const Icon = item.icon;
                return (
                  <li key={item.key}>
                    <Link
                      href={item.href}
                      className={cn(
                        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors",
                        active
                          ? "bg-brand-50 font-medium text-brand-600"
                          : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
                      )}
                      aria-current={active ? "page" : undefined}
                    >
                      <Icon size={16} className="shrink-0" />
                      <span className="flex-1 truncate">{item.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </div>
  );
}
