"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  IconSearch,
  IconUsersGroup,
  IconFileText,
  IconTable,
  IconLayoutDashboard,
} from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { Badge } from "@/components/ui/badge";
import { getUserMeta } from "@/lib/auth";
import { accentFor } from "@/lib/ui/color";
import { aiStatusLabel, aiStatusTone, timeAgo } from "@/lib/ui/format";
import { useCurrentUser, useProjectSummaries } from "@/lib/ui/use-shell-data";
import type {
  CurrentUser,
  ProjectSummary,
  TenantSummary,
} from "@/lib/ui/types";

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

function StatChip({
  icon: StatIcon,
  value,
  label,
}: {
  icon: typeof IconFileText;
  value: number;
  label: string;
}) {
  return (
    <span
      className="flex items-center gap-1.5 text-ink-secondary"
      title={`${value} ${label}`}
    >
      <StatIcon size={14} className="text-ink-tertiary" />
      <span className="tabular-nums">{value}</span>
    </span>
  );
}

function SharedProjectCard({ project }: { project: ProjectSummary }) {
  const accent = project.accent ?? accentFor(project.id);
  return (
    <Link
      href={`/projects/${project.id}`}
      className="group flex h-full flex-col rounded-lg border border-line-tertiary bg-bg-primary transition hover:border-brand-500 hover:shadow-sm focus:border-brand-500 focus:outline-none"
      data-testid={`shared-project-${project.id}`}
    >
      <span className="h-1 rounded-t-lg" style={{ background: accent }} />
      <span className="flex flex-1 flex-col p-4">
        <span className="flex items-start justify-between gap-2">
          <span className="text-[13px] font-semibold text-ink-primary group-hover:text-brand-700">
            {project.name}
          </span>
          <Badge tone={aiStatusTone(project.aiStatus)}>
            {aiStatusLabel(project.aiStatus)}
          </Badge>
        </span>
        <span className="mt-1 block text-[12px] text-ink-tertiary">
          Updated {timeAgo(project.updatedLabel)}
        </span>
        <span className="mt-4 flex items-center gap-4 text-[12px]">
          <StatChip
            icon={IconFileText}
            value={project.documentCount}
            label="documents"
          />
          <StatChip
            icon={IconTable}
            value={project.queryCount}
            label="tables"
          />
          <StatChip
            icon={IconLayoutDashboard}
            value={project.dashboardCount}
            label="dashboards"
          />
        </span>
      </span>
    </Link>
  );
}

export default function SharedProjectsPage() {
  const router = useRouter();
  const { data: identity } = useCurrentUser();
  const { data: allProjects, isLoading } = useProjectSummaries();
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!getUserMeta()) router.replace("/login");
  }, [router]);

  const shared = useMemo(
    () => (allProjects ?? []).filter((p) => p.visibility === "shared"),
    [allProjects],
  );

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return term
      ? shared.filter((p) => p.name.toLowerCase().includes(term))
      : shared;
  }, [shared, search]);

  const user = identity?.user ?? FALLBACK_USER;
  const tenant = identity?.tenant ?? FALLBACK_TENANT;

  return (
    <AppShell
      mode="home"
      activeNav="projects"
      tenant={tenant}
      user={user}
      counts={{ projects: allProjects?.length }}
      centered
      topBarLeft={
        <span className="flex items-center gap-2 text-h2 text-ink-primary">
          <IconUsersGroup size={18} className="text-ink-tertiary" />
          Shared Projects
        </span>
      }
    >
      <div className="space-y-4 pb-8">
        <p className="text-[13px] text-ink-secondary">
          Projects your teammates have shared with the organization.
        </p>

        <div className="relative max-w-sm">
          <IconSearch
            size={15}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search shared projects…"
            className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary pl-8 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
          />
        </div>

        {isLoading && (
          <p className="py-10 text-center text-[13px] text-ink-tertiary">
            Loading shared projects…
          </p>
        )}

        {!isLoading && rows.length === 0 && (
          <div className="rounded-lg border border-dashed border-line-secondary px-4 py-12 text-center">
            <p className="text-[13px] text-ink-secondary">
              {search
                ? "No shared projects match your search."
                : "No projects have been shared with your organization yet."}
            </p>
            <Link
              href="/projects"
              className="mt-2 inline-block text-[13px] text-brand-700 hover:underline"
            >
              Browse all projects
            </Link>
          </div>
        )}

        {rows.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {rows.map((p) => (
              <SharedProjectCard key={p.id} project={p} />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
