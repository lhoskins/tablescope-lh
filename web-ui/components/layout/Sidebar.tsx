"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const mainItems = [
  { href: "/dashboard", label: "Overview" },
  { href: "/projects", label: "Projects" },
  { href: "/upload", label: "Upload" },
  { href: "/query", label: "Query" },
  { href: "/scopes", label: "Scopes" },
];

const adminItems = [
  { href: "/admin/users", label: "Users" },
  { href: "/admin/tenants", label: "Tenants" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-56 shrink-0">
      <nav className="space-y-1">
        {mainItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "block rounded-md px-3 py-2 text-sm font-medium",
              pathname === item.href
                ? "bg-brand text-brand-fg"
                : "text-slate-700 hover:bg-slate-100"
            )}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="mt-6 border-t border-slate-200 pt-4">
        <p className="mb-2 px-3 text-xs font-semibold uppercase text-slate-400">
          Admin
        </p>
        <nav className="space-y-1">
          {adminItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "block rounded-md px-3 py-2 text-sm font-medium",
                pathname === item.href
                  ? "bg-brand text-brand-fg"
                  : "text-slate-700 hover:bg-slate-100"
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </aside>
  );
}
