"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  IconBook,
  IconBuildingBank,
  IconMathFunction,
  IconBrain,
  IconPhoto,
  IconShieldLock,
  IconFolders,
  IconLock,
  IconChevronRight,
} from "@tabler/icons-react";
import { getUserMeta } from "@/lib/auth";
import { useCurrentUser } from "@/lib/ui/use-shell-data";

interface SettingCard {
  key: string;
  label: string;
  description: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}

export default function AdminSettingsPage() {
  const { data: identity } = useCurrentUser();
  const [tenantId, setTenantId] = useState<number | null>(null);

  useEffect(() => {
    const meta = getUserMeta();
    if (meta) setTenantId(meta.tenant_id);
  }, []);

  const isAdmin =
    identity?.user.isSuperAdmin ||
    ["tenant_admin", "admin", "root_admin"].includes(
      identity?.user.rawRole ?? "",
    );

  const settings: SettingCard[] = [
    {
      key: "reference-library",
      label: "Reference Library",
      description: "Manage shared reference entries for your organization.",
      href: "/reference-library",
      icon: IconBook,
    },
    {
      key: "company-reference-library",
      label: "Company Library",
      description: "Manage company-specific reference data and documents.",
      href: "/reference-library/company",
      icon: IconBuildingBank,
    },
    {
      key: "branding",
      label: "Branding",
      description: "Upload your company logo for the top header and emails.",
      href: "/admin/branding",
      icon: IconPhoto,
    },
    {
      key: "allowed-domains",
      label: "Allowed Domains",
      description: "Control which email domains can join this workspace.",
      href: "/admin/allowed-domains",
      icon: IconShieldLock,
    },
    {
      key: "repositories",
      label: "Repositories",
      description: "Connect and manage enterprise repositories and UNC paths.",
      href: "/admin/repositories",
      icon: IconFolders,
    },
    {
      key: "my-tenant",
      label: "My Tenant",
      description: "Manage tenant details and tenant-wide 2FA enforcement.",
      href: tenantId ? `/admin/tenants/${tenantId}` : "/admin/tenants",
      icon: IconBuildingBank,
    },
    {
      key: "analytical-methods",
      label: "Analytical Methods",
      description: "Activate and review analytical method catalog entries.",
      href: "/admin/analytical-methods",
      icon: IconMathFunction,
    },
    {
      key: "ai-governance",
      label: "AI Governance",
      description: "Review AI governance policies and audit history.",
      href: "/admin/ai-governance",
      icon: IconBrain,
    },
    {
      key: "two-factor",
      label: "Two-factor authentication",
      description: "Require all members to complete SMS MFA for this tenant.",
      href: tenantId ? `/admin/tenants/${tenantId}` : "/admin/tenants",
      icon: IconLock,
    },
  ];

  if (!isAdmin) {
    return (
      <section className="max-w-3xl">
        <h1 className="text-2xl font-semibold text-ink-primary">Settings</h1>
        <p className="mt-2 text-sm text-ink-tertiary">
          You do not have permission to view these settings.
        </p>
      </section>
    );
  }

  return (
    <section className="max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-ink-primary">Settings</h1>
        <p className="mt-1 text-sm text-ink-tertiary">
          Manage workspace configuration, branding, and security settings.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        {settings.map((s) => {
          const Icon = s.icon;
          return (
            <Link
              key={s.key}
              href={s.href}
              className="group flex items-start gap-4 rounded-lg border border-line-secondary bg-bg-primary p-4 transition-colors hover:border-brand-500 hover:bg-brand-50"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-brand-50 text-brand-600 group-hover:bg-white">
                <Icon size={20} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-ink-primary">
                    {s.label}
                  </h2>
                  <IconChevronRight
                    size={14}
                    className="ml-auto shrink-0 text-ink-tertiary group-hover:text-brand-600"
                  />
                </div>
                <p className="mt-0.5 text-xs text-ink-tertiary">
                  {s.description}
                </p>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
