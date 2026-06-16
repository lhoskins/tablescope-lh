"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { IconSearch, IconUpload, IconSparkles } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { SharedByBadge } from "@/components/tablescope/shared-by-badge";
import { Badge } from "@/components/ui/badge";
import { getUserMeta } from "@/lib/auth";
import {
  useCurrentUser,
  useProjectSummaries,
  useAllDataSources,
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

export default function HomeDataSourcesPage() {
  const router = useRouter();
  const { data: identity } = useCurrentUser();
  const { data: projects } = useProjectSummaries();
  const { data, isLoading } = useAllDataSources();
  const [search, setSearch] = useState("");
  const [dragActive, setDragActive] = useState(false);

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
      activeNav="data-sources"
      tenant={tenant}
      user={user}
      counts={{ projects: projects?.length }}
      centered
      topBarLeft={
        <span className="text-h2 text-ink-primary">Data Sources</span>
      }
    >
      <div className="space-y-4">
        {/* AI-assisted file upload dropzone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            // TODO: wire to AIFileUploadWizard once project selection is added
          }}
          className={`flex items-center gap-4 rounded-lg border-2 border-dashed p-5 transition-colors ${
            dragActive
              ? "border-brand-500 bg-brand-50/40"
              : "border-line-tertiary bg-bg-secondary/50"
          }`}
        >
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-500">
            <IconSparkles size={20} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-medium text-ink-primary">
              AI-Assisted File Upload
            </p>
            <p className="text-small text-ink-tertiary">
              Drag &amp; drop files here to upload with AI-powered column
              detection and profiling.
            </p>
          </div>
          <label className="flex cursor-pointer items-center gap-1.5 rounded-md border border-line-secondary bg-bg-primary px-3 py-2 text-[12px] font-medium text-ink-secondary hover:bg-bg-secondary">
            <IconUpload size={14} />
            Browse
            <input type="file" className="hidden" multiple />
          </label>
        </div>

        <div className="relative max-w-sm">
          <IconSearch
            size={15}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search data sources…"
            className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary pl-8 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-line-tertiary bg-bg-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                <th className="px-4 py-2.5 font-medium">Name</th>
                <th className="px-4 py-2.5 font-medium">Project Assigned</th>
                <th className="px-4 py-2.5 font-medium">Shared by</th>
                <th className="px-4 py-2.5 font-medium">Type</th>
                <th className="px-4 py-2.5 font-medium">Date Created</th>
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
                      ? "No data sources match your search."
                      : "No data sources yet."}
                  </td>
                </tr>
              )}
              {isLoading && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-10 text-center text-ink-tertiary"
                  >
                    Loading data sources…
                  </td>
                </tr>
              )}
              {rows.map((d) => (
                <tr
                  key={`${d.kind}-${d.id}`}
                  className="cursor-pointer border-b border-line-tertiary last:border-0 hover:bg-bg-tertiary"
                  onClick={() =>
                    router.push(`/projects/${d.projectId}/data-sources`)
                  }
                >
                  <td className="px-4 py-3">
                    <span className="font-medium text-ink-primary">
                      {d.name}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/projects/${d.projectId}`}
                      className="text-ink-secondary hover:text-brand-700"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {d.projectName}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <SharedByBadge value={d.sharedBy} />
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={d.kind === "database" ? "success" : "neutral"}>
                      {d.kind === "database" ? "Connected" : "File"}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-ink-tertiary">
                    {formatDate(d.createdAt)}
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
