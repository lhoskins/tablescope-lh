"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { getUserMeta } from "@/lib/auth";
import { cn } from "@/lib/cn";

type NavItem = { href: string; label: string };

const pillItems: NavItem[] = [
  { href: "/upload", label: "Datasources" },
  { href: "/projects", label: "Projects" },
];

const otherItems: NavItem[] = [];

const tenantAdminItems: NavItem[] = [
  { href: "/admin/users", label: "Users" },
  { href: "/admin/tenants", label: "My Tenant" },
];

// root_admin is a tenant superset: user management + tenant lifecycle/VDB.
const rootAdminItems: NavItem[] = [
  { href: "/admin/users", label: "Users" },
  { href: "/admin/tenants", label: "My Tenant" },
];

const superAdminItems: NavItem[] = [
  { href: "/admin/users", label: "Users" },
  { href: "/admin/tenants", label: "Tenant Provisioning" },
  { href: "/admin/data-planes", label: "Data Planes (VPN)" },
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

function ToggleIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("transition-transform", collapsed && "rotate-180")}
    >
      <rect width="18" height="18" x="3" y="3" rx="2" />
      <path d="M9 3v18" />
      {collapsed ? (
        <path d="m14 9 3 3-3 3" />
      ) : (
        <path d="m16 15-3-3 3-3" />
      )}
    </svg>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const meta = getUserMeta();
  const isSuperAdmin = meta?.is_super_admin ?? false;
  const role = meta?.role;
  const adminNav = isSuperAdmin
    ? superAdminItems
    : role === "root_admin"
      ? rootAdminItems
      : role === "tenant_admin" || role === "admin"
        ? tenantAdminItems
        : [];

  const [collapsed, setCollapsed] = useState(false);
  const toggle = useCallback(() => setCollapsed((v) => !v), []);

  if (collapsed) {
    return (
      <aside className="w-10 shrink-0">
        <button
          onClick={toggle}
          className="rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
          aria-label="Open sidebar"
          title="Open sidebar"
        >
          <ToggleIcon collapsed />
        </button>
      </aside>
    );
  }

  return (
    <aside className="w-56 shrink-0">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase text-slate-400">
          Navigation
        </span>
        <button
          onClick={toggle}
          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          aria-label="Collapse sidebar"
          title="Collapse sidebar"
        >
          <ToggleIcon collapsed={false} />
        </button>
      </div>

      {/* Pill navigation */}
      <div className="flex flex-col gap-2 mb-4">
        {pillItems.map((item) => (
          <PillLink
            key={item.href}
            item={item}
            active={pathname === item.href || pathname.startsWith(item.href + "/")}
          />
        ))}
      </div>

      {/* Regular nav links */}
      {otherItems.length > 0 && (
        <nav className="space-y-1">
          {otherItems.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              active={pathname === item.href}
            />
          ))}
        </nav>
      )}

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
