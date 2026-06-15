"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { NewProjectDialog } from "@/components/tablescope/project/new-project-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getUserMeta } from "@/lib/auth";
import { aiStatusLabel, aiStatusTone, timeAgo } from "@/lib/ui/format";
import { accentFor } from "@/lib/ui/color";
import { useCurrentUser, useProjectSummaries } from "@/lib/ui/use-shell-data";
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

export default function ProjectsPage() {
  const router = useRouter();
  const { data: identity } = useCurrentUser();
  const { data: projects } = useProjectSummaries();

  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    if (!getUserMeta()) {
      router.replace("/login");
      return;
    }
    if (new URLSearchParams(window.location.search).get("new") != null) {
      setShowCreate(true);
    }
  }, [router]);

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    const all = projects ?? [];
    return term ? all.filter((p) => p.name.toLowerCase().includes(term)) : all;
  }, [projects, search]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  return (
    <AppShell
      mode="home"
      activeNav="projects"
      tenant={tenant}
      user={user}
      counts={{ projects: projects?.length }}
      centered
      topBarLeft={<span className="text-h2 text-ink-primary">Projects</span>}
      topBarRight={
        <Button variant="primary" size="md" onClick={() => setShowCreate(true)}>
          <IconPlus size={15} />
          New project
        </Button>
      }
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
            placeholder="Search projects…"
            className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary pl-8 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-line-tertiary bg-bg-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                <th className="px-4 py-2.5 font-medium">Project</th>
                <th className="px-4 py-2.5 text-right font-medium">Documents</th>
                <th className="px-4 py-2.5 text-right font-medium">Queries</th>
                <th className="px-4 py-2.5 text-right font-medium">Dashboards</th>
                <th className="px-4 py-2.5 font-medium">AI Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-10 text-center text-ink-tertiary"
                  >
                    {search
                      ? "No projects match your search."
                      : "No projects yet. Create your first one."}
                  </td>
                </tr>
              )}
              {rows.map((p) => (
                <tr
                  key={p.id}
                  className="border-b border-line-tertiary last:border-0 hover:bg-bg-tertiary"
                >
                  <td className="px-4 py-3">
                    <Link
                      href={`/projects/${p.id}`}
                      className="flex items-center gap-2.5"
                    >
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ background: p.accent ?? accentFor(p.id) }}
                      />
                      <span>
                        <span className="block font-medium text-ink-primary">
                          {p.name}
                        </span>
                        <span className="block text-small text-ink-tertiary">
                          Updated {timeAgo(p.updatedLabel)} ·{" "}
                          {p.visibility === "shared" ? "Shared" : "Private"}
                        </span>
                      </span>
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-ink-secondary">
                    {p.documentCount}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-ink-secondary">
                    {p.queryCount}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-ink-secondary">
                    {p.dashboardCount}
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={aiStatusTone(p.aiStatus)}>
                      {aiStatusLabel(p.aiStatus)}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <NewProjectDialog open={showCreate} onClose={() => setShowCreate(false)} />
    </AppShell>
  );
}
