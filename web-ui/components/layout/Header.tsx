"use client";

import Link from "next/link";
import { TenantSwitcher } from "./TenantSwitcher";

export function Header() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
        <Link
          href="/"
          className="text-lg font-semibold text-slate-900"
        >
          Tablescope
        </Link>
        <div className="flex items-center gap-4">
          <TenantSwitcher />
        </div>
      </div>
    </header>
  );
}
