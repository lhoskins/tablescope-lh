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
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import type { CurrentUser } from "@/lib/ui/types";

export interface SettingsNavItem {
  key: string;
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  section: string;
  visible: () => boolean;
}

export function useSettingsNavItems(user?: CurrentUser): {
  sections: { heading: string; items: SettingsNavItem[] }[];
} {
  const isAdmin =
    user?.isSuperAdmin ||
    ["admin", "tenant_admin", "root_admin"].includes(user?.rawRole ?? "");
  const isPlatformAdmin =
    user?.isSuperAdmin || user?.rawRole === "root_admin";

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
      visible: () => isAdmin,
    },
    {
      key: "reference-library",
      label: "Reference Library",
      href: "/admin/settings/reference-library",
      icon: IconBook,
      section: "Knowledge",
      visible: () => isAdmin,
    },
    {
      key: "company-library",
      label: "Company Library",
      href: "/admin/settings/company-library",
      icon: IconBuildingBank,
      section: "Knowledge",
      visible: () => isAdmin,
    },
    {
      key: "security",
      label: "Two-factor authentication",
      href: "/admin/settings/security",
      icon: IconShieldLock,
      section: "Security",
      visible: () => isAdmin,
    },
    {
      key: "allowed-domains",
      label: "Allowed Domains",
      href: "/admin/settings/allowed-domains",
      icon: IconLock,
      section: "Security",
      visible: () => isAdmin,
    },
    {
      key: "repositories",
      label: "Repositories",
      href: "/admin/settings/repositories",
      icon: IconFolders,
      section: "Integrations",
      visible: () => isAdmin,
    },
    {
      key: "analytical-methods",
      label: "Analytical Methods",
      href: "/admin/settings/analytical-methods",
      icon: IconMathFunction,
      section: "Intelligence",
      visible: () => isAdmin,
    },
    {
      key: "ai-governance",
      label: "AI Governance",
      href: "/admin/settings/ai-governance",
      icon: IconBrain,
      section: "Intelligence",
      visible: () => isAdmin,
    },
    {
      key: "platform-tenants",
      label: "Tenants",
      href: "/admin/settings/platform/tenants",
      icon: IconServer,
      section: "Platform Administration",
      visible: () => isPlatformAdmin,
    },
    {
      key: "admin-users",
      label: "Users",
      href: "/admin/users",
      icon: IconUsers,
      section: "Platform Administration",
      visible: () => isPlatformAdmin,
    },
    {
      key: "llm-framework",
      label: "LLM Framework",
      href: "/admin/settings/llm-framework",
      icon: IconRobot,
      section: "Platform Administration",
      visible: () => isPlatformAdmin,
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

export function SettingsNav({ user }: SettingsNavProps) {
  const pathname = usePathname();
  const { sections } = useSettingsNavItems(user);

  return (
    <div className="space-y-6">
      <label className="block md:hidden">
        <span className="sr-only">Settings section</span>
        <select
          className="w-full rounded-md border border-line-secondary bg-bg-primary px-3 py-2 text-sm text-ink-primary focus:border-brand-500 focus:outline-none"
          value={pathname}
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
                const active = pathname.startsWith(item.href);
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
