"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import { AppShell } from "@/components/tablescope/app-shell";
import { NewProjectDialog } from "@/components/tablescope/project/new-project-dialog";
import { ProjectRowActions } from "@/components/tablescope/project/project-row-actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ToastViewport, useToasts } from "@/components/ui/toast";
import { getUserMeta } from "@/lib/auth";
import { aiStatusLabel, aiStatusTone, timeAgo } from "@/lib/ui/format";
import { accentFor } from "@/lib/ui/color";
import { useCurrentUser, useProjectSummaries } from "@/lib/ui/use-shell-data";
import type {
  CurrentUser,
  ProjectSummary,
  TenantSummary,
} from "@/lib/ui/types";
import type { ToastTone } from "@/components/ui/toast";

type PushToast = (message: string, tone?: ToastTone) => void;

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
  const { toasts, push, dismiss } = useToasts();

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

  const privateRows = useMemo(
    () => rows.filter((p) => p.visibility !== "shared"),
    [rows],
  );
  const sharedRows = useMemo(
    () => rows.filter((p) => p.visibility === "shared"),
    [rows],
  );

  const [openPrivate, setOpenPrivate] = useState(true);
  const [openShared, setOpenShared] = useState(true);

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

        <ProjectAccordionSection
          title="Private"
          count={privateRows.length}
          open={openPrivate}
          onToggle={() => setOpenPrivate((v) => !v)}
        >
          <ProjectTable
            rows={privateRows}
            emptyLabel={
              search
                ? "No private projects match your search."
                : "No private projects yet."
            }
            onToast={push}
          />
        </ProjectAccordionSection>

        <ProjectAccordionSection
          title="Shared"
          count={sharedRows.length}
          open={openShared}
          onToggle={() => setOpenShared((v) => !v)}
        >
          <ProjectTable
            rows={sharedRows}
            emptyLabel={
              search
                ? "No shared projects match your search."
                : "No shared projects yet."
            }
            onToast={push}
          />
        </ProjectAccordionSection>
      </div>

      <NewProjectDialog open={showCreate} onClose={() => setShowCreate(false)} />
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </AppShell>
  );
}

function ProjectAccordionSection({
  title,
  count,
  open,
  onToggle,
  children,
}: {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-line-tertiary bg-bg-primary">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-bg-tertiary"
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center text-body font-semibold text-ink-tertiary">
          {open ? "−" : "+"}
        </span>
        <span className="text-h3 text-ink-primary">
          {title} ({count})
        </span>
      </button>
      {open && <div className="border-t border-line-tertiary">{children}</div>}
    </div>
  );
}

function ProjectTable({
  rows,
  emptyLabel,
  onToast,
}: {
  rows: ProjectSummary[];
  emptyLabel: string;
  onToast: PushToast;
}) {
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="border-b border-line-tertiary bg-bg-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
          <th className="px-4 py-2.5 font-medium">Project</th>
          <th className="px-4 py-2.5 text-right font-medium">Documents</th>
          <th className="px-4 py-2.5 text-right font-medium">Queries</th>
          <th className="px-4 py-2.5 text-right font-medium">Dashboards</th>
          <th className="px-4 py-2.5 font-medium">AI Status</th>
          <th className="w-12 px-4 py-2.5 text-right font-medium">Actions</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td colSpan={6} className="px-4 py-10 text-center text-ink-tertiary">
              {emptyLabel}
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
            <td className="px-4 py-3">
              <ProjectRowActions
                project={{ id: p.id, name: p.name }}
                onToast={onToast}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
