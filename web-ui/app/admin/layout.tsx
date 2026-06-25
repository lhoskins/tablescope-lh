"use client";

import { type ReactNode, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/tablescope/app-shell";
import { getUserMeta } from "@/lib/auth";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import type { CurrentUser, NavKey, TenantSummary } from "@/lib/ui/types";

const FALLBACK_USER: CurrentUser = {
  name: "",
  email: "",
  role: "",
  tenantName: "",
  initials: "··",
};
const FALLBACK_TENANT: TenantSummary = {
  name: "Tablescope",
  slug: "",
  initials: "TS",
};

function activeNavFor(pathname: string): NavKey {
  if (pathname.startsWith("/admin/data-planes")) return "admin-data-planes";
  if (pathname.startsWith("/admin/tenants")) return "admin-tenants";
  if (pathname.startsWith("/admin/allowed-domains")) return "admin-allowed-domains";
  return "admin-users";
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { data: identity } = useCurrentUser();

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  return (
    <AppShell
      mode="home"
      activeNav={activeNavFor(pathname)}
      tenant={tenant}
      user={user}
    >
      {children}
    </AppShell>
  );
}
