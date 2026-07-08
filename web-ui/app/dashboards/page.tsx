"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { IconSearch, IconTrash } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { OwnerBadge } from "@/components/tablescope/owner-badge";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api-client";
import { getUserMeta } from "@/lib/auth";
import {
  useCurrentUser,
  useProjectSummaries,
  useAllDashboards,
} from "@/lib/ui/use-shell-data";
import type { CurrentUser, TenantSummary } from "@/lib/ui/types";

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

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function HomeDashboardsPage() {
  const router = useRouter();
  const { data: identity } = useCurrentUser();
  const { data: projects } = useProjectSummaries();
  const { data, isLoading } = useAllDashboards();
  const [search, setSearch] = useState("");
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: (d: { projectId: number; id: number }) =>
      apiClient.delete(`/api/projects/${d.projectId}/dashboards/${d.id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["home", "dashboards-all"] }),
  });

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const rows = useMemo(() => {
    const all = data ?? [];
    const term = search.trim().toLowerCase();
    return term
      ? all.filter(
          (d) =>
            d.name.toLowerCase().includes(term) ||
            d.projectName.toLowerCase().includes(term),
        )
      : all;
  }, [data, search]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  return (
    <AppShell
      mode="home"
      activeNav="dashboards"
      tenant={tenant}
      user={user}
      counts={{ projects: projects?.length }}
      centered
      topBarLeft={<span className="text-h2 text-ink-primary">Dashboards</span>}
    >
      <div className="space-y-4">
        <div className="relative max-w-sm">
          <IconSearch
            size={15}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search dashboards…"
            className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary pl-8 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-line-tertiary bg-bg-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                <th className="px-4 py-2.5 font-medium">Name</th>
                <th className="px-4 py-2.5 font-medium">Project Assigned</th>
                <th className="px-4 py-2.5 font-medium">Owner</th>
                <th className="px-4 py-2.5 font-medium">Date Created</th>
                <th className="w-10 px-4 py-2.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {!isLoading && rows.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-10 text-center text-ink-tertiary"
                  >
                    {search
                      ? "No dashboards match your search."
                      : "No dashboards yet."}
                  </td>
                </tr>
              )}
              {isLoading && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-10 text-center text-ink-tertiary"
                  >
                    Loading dashboards…
                  </td>
                </tr>
              )}
              {rows.map((d) => (
                <tr
                  key={d.id}
                  className="border-b border-line-tertiary last:border-0 hover:bg-bg-tertiary"
                >
                  <td className="px-4 py-3">
                    <Link
                      href={`/projects/${d.projectId}/dashboards/${d.id}`}
                      className="flex items-center gap-2 font-medium text-ink-primary hover:text-brand-700"
                    >
                      {d.name}
                      {d.status?.toLowerCase() === "published" && (
                        <Badge tone="success">Published</Badge>
                      )}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/projects/${d.projectId}`}
                      className="text-ink-secondary hover:text-brand-700"
                    >
                      {d.projectName}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <OwnerBadge name={d.ownerName} />
                  </td>
                  <td className="px-4 py-3 text-ink-tertiary">
                    {formatDate(d.createdAt)}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      title="Delete dashboard"
                      aria-label={`Delete dashboard ${d.name}`}
                      disabled={deleteMutation.isPending}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Delete dashboard "${d.name}"? This cannot be undone.`,
                          )
                        ) {
                          deleteMutation.mutate({
                            projectId: d.projectId,
                            id: d.id,
                          });
                        }
                      }}
                      className="text-ink-tertiary hover:text-red-600 disabled:opacity-50"
                    >
                      <IconTrash size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}
