"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { getUserMeta } from "@/lib/auth";
import { cn } from "@/lib/cn";

type NavItem = { href: string; label: string };

const pillItems: NavItem[] = [
  { href: "/projects", label: "Projects" },
  { href: "/query", label: "Queries" },
  { href: "/upload", label: "Datasources" },
];

const otherItems: NavItem[] = [
  { href: "/dashboard", label: "Overview" },
  { href: "/scopes", label: "Scopes" },
];

const tenantAdminItems: NavItem[] = [
  { href: "/admin/users", label: "Users" },
  { href: "/admin/tenants", label: "My Tenant" },
];

const superAdminItems: NavItem[] = [
  { href: "/admin/users", label: "Users" },
  { href: "/admin/tenants", label: "Tenant Provisioning" },
];

function PillLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      className={cn(
        "inline-flex items-center rounded-full px-4 py-1.5 text-sm font-medium transition-colors",
        active
          ? "bg-brand text-brand-fg shadow-sm"
          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
      )}
    >
      {item.label}
    </Link>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      className={cn(
        "block rounded-md px-3 py-2 text-sm font-medium",
        active
          ? "bg-brand text-brand-fg"
          : "text-slate-700 hover:bg-slate-100"
      )}
    >
      {item.label}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const meta = getUserMeta();
  const isSuperAdmin = meta?.is_super_admin ?? false;
  const isAdmin = meta?.role === "admin";

  const adminNav = isSuperAdmin ? superAdminItems : isAdmin ? tenantAdminItems : [];

  return (
    <aside className="w-56 shrink-0">
      {/* Pill navigation */}
      <div className="flex flex-wrap gap-2 mb-4">
        {pillItems.map((item) => (
          <PillLink
            key={item.href}
            item={item}
            active={pathname === item.href || pathname.startsWith(item.href + "/")}
          />
        ))}
      </div>

      {/* Regular nav links */}
      <nav className="space-y-1">
        {otherItems.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={pathname === item.href}
          />
        ))}
      </nav>

      {/* Admin section */}
      {adminNav.length > 0 && (
        <div className="mt-6 border-t border-slate-200 pt-4">
          <p className="mb-2 px-3 text-xs font-semibold uppercase text-slate-400">
            Admin
          </p>
          <nav className="space-y-1">
            {adminNav.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                active={pathname === item.href}
              />
            ))}
          </nav>
        </div>
      )}
    </aside>
  );
}
