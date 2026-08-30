"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  IconChevronRight,
  IconChevronDown,
  IconFolders,
  IconPlus,
  IconTable,
  IconFileText,
  IconDatabase,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { accentFor } from "@/lib/ui/color";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import {
  useProjectArchivedQueries,
  useProjectDataSources,
  useProjectDocuments,
  useProjectQueries,
} from "@/lib/ui/use-project-data";
import { loadWorkspaceTabs } from "@/components/tablescope/project/workspace/workspace-tabs-storage";
import type { ProjectSummary } from "@/lib/ui/types";

/**
 * The sidebar's persistent Projects section (`docs/ux-workspace-redesign-gap-analysis.md`
 * §2): a disclosure toggle -- not a plain link -- that expands into
 * PRIVATE/SHARED grouped project lists. The current project (when inside
 * one) auto-expands its own Tables/Documents/Data Sources asset subtree,
 * with items highlighted when they're pinned into the open workspace's tab
 * strip. This replaces the old flat "Other Projects" block and its 6-item
 * cap -- every project the user can see is listed here, uncapped.
 */
export function ProjectsTree({
  currentProjectId,
  collapsed,
}: {
  currentProjectId?: string | null;
  collapsed: boolean;
}) {
  const { data: projects } = useProjectSummaries();
  const [open, setOpen] = useState(Boolean(currentProjectId));

  useEffect(() => {
    if (currentProjectId) setOpen(true);
  }, [currentProjectId]);

  const all = useMemo(() => projects ?? [], [projects]);
  const privateProjects = useMemo(
    () => all.filter((p) => p.visibility === "private"),
    [all],
  );
  const sharedProjects = useMemo(
    () => all.filter((p) => p.visibility === "shared"),
    [all],
  );

  if (collapsed) {
    return (
      <Link
        href="/projects"
        title="Projects"
        aria-label="Projects"
        className="flex h-9 w-9 items-center justify-center rounded-md text-ink-tertiary hover:bg-bg-secondary hover:text-ink-primary"
      >
        <IconFolders size={18} stroke={1.8} />
      </Link>
    );
  }

  return (
    <div className="space-y-0.5">
      <div className="group flex items-center rounded-md pr-1 text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex flex-1 items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px]"
        >
          {open ? (
            <IconChevronDown size={13} stroke={1.8} className="shrink-0 text-ink-tertiary" />
          ) : (
            <IconChevronRight size={13} stroke={1.8} className="shrink-0 text-ink-tertiary" />
          )}
          <IconFolders size={15} stroke={1.8} className="shrink-0" />
          <span className="flex-1 truncate">Projects</span>
          {all.length > 0 && (
            <span className="rounded-full bg-brand-50 px-1.5 text-[11px] font-medium text-brand-700">
              {all.length}
            </span>
          )}
        </button>
        <Link
          href="/projects?new=1"
          title="New project"
          aria-label="New project"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-ink-tertiary opacity-0 hover:bg-bg-primary hover:text-ink-primary group-hover:opacity-100"
        >
          <IconPlus size={13} />
        </Link>
      </div>

      {open && (
        <div className="ml-1 space-y-2 border-l border-line-tertiary pb-1 pl-2">
          <ProjectVisibilityGroup
            label="PRIVATE"
            projects={privateProjects}
            currentProjectId={currentProjectId}
          />
          <ProjectVisibilityGroup
            label="SHARED"
            projects={sharedProjects}
            currentProjectId={currentProjectId}
          />
        </div>
      )}
    </div>
  );
}

function ProjectVisibilityGroup({
  label,
  projects,
  currentProjectId,
}: {
  label: string;
  projects: ProjectSummary[];
  currentProjectId?: string | null;
}) {
  if (projects.length === 0) return null;
  return (
    <div className="space-y-0.5">
      <div className="px-2 pb-0.5 pt-1 text-[10px] font-semibold uppercase tracking-wide text-ink-tertiary">
        {label} ({projects.length})
      </div>
      {projects.map((p) => (
        <div key={p.id}>
          <Link
            href={`/projects/${p.id}`}
            className={cn(
              "flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px]",
              p.id === currentProjectId
                ? "bg-brand-50 font-semibold text-brand-500"
                : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
            )}
          >
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: p.accent ?? accentFor(p.id) }}
            />
            <span className="flex-1 truncate">{p.name}</span>
          </Link>
          {p.id === currentProjectId && <ProjectAssetTree projectId={p.id} />}
        </div>
      ))}
    </div>
  );
}

function ProjectAssetTree({ projectId }: { projectId: string }) {
  const { data: queries } = useProjectQueries(projectId);
  const { data: archivedQueries } = useProjectArchivedQueries(projectId);
  const { data: documents } = useProjectDocuments(projectId);
  const { data: dataSources } = useProjectDataSources(projectId);
  const [openTabKeys, setOpenTabKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    const tabs = loadWorkspaceTabs(projectId);
    setOpenTabKeys(new Set(tabs.map((t) => `${t.type}:${t.id}`)));
  }, [projectId]);

  const addHref = `/projects/${projectId}/data-source-builder`;

  // Tables open on the hand-built ones only. A project with dozens of
  // AI-generated tables would otherwise bury them, so those and the archive
  // sit one level deeper, behind "More".
  const tableItem = (q: { id: number; name: string }) => ({
    key: `table:${q.id}`,
    label: q.name,
    href: `/projects/${projectId}/queries?q=${q.id}`,
  });
  const tables = queries ?? [];
  const manualTables = tables.filter((q) => !q.ai_generated);
  const aiTables = tables.filter((q) => q.ai_generated);
  const archivedTables = archivedQueries ?? [];

  return (
    <div className="ml-1.5 space-y-1 border-l border-line-tertiary pb-1 pl-2.5">
      <AssetGroup
        label="Tables"
        icon={IconTable}
        addHref={addHref}
        items={manualTables.map(tableItem)}
        count={tables.length + archivedTables.length}
        more={[
          {
            key: "ai",
            label: "AI-generated",
            items: aiTables.map(tableItem),
          },
          {
            key: "archive",
            label: "Archived",
            items: archivedTables.map(tableItem),
          },
        ]}
        openTabKeys={openTabKeys}
      />
      <AssetGroup
        label="Documents"
        icon={IconFileText}
        addHref={addHref}
        items={(documents ?? []).map((d) => ({
          key: `document:${d.id}`,
          label: d.title,
          href: `/projects/${projectId}/documents?doc=${d.id}`,
        }))}
        openTabKeys={openTabKeys}
      />
      <AssetGroup
        label="Data Sources"
        icon={IconDatabase}
        addHref={addHref}
        items={(dataSources ?? []).map((d) => ({
          key: `data_source:${typeof d.id === "number" ? d.id : d.lifecycleId}`,
          label: d.fileName,
          href: `/projects/${projectId}/data-sources?ds=${encodeURIComponent(d.lifecycleId)}`,
        }))}
        openTabKeys={openTabKeys}
      />
    </div>
  );
}

type AssetItem = { key: string; label: string; href: string };

function AssetGroup({
  label,
  icon: Icon,
  addHref,
  items,
  count,
  more,
  openTabKeys,
}: {
  label: string;
  icon: typeof IconTable;
  addHref: string;
  items: AssetItem[];
  /** Badge override for groups whose list is only part of the whole (Tables
   *  shows every table it holds, including the ones parked under "More"). */
  count?: number;
  /** Secondary sub-groups, collapsed behind a "More" node below `items`. */
  more?: { key: string; label: string; items: AssetItem[] }[];
  openTabKeys: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  const badge = count ?? items.length;
  return (
    <div>
      <div className="group flex items-center rounded-md pr-1 text-ink-tertiary hover:bg-bg-secondary hover:text-ink-secondary">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex flex-1 items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-[12px]"
        >
          {open ? <IconChevronDown size={11} /> : <IconChevronRight size={11} />}
          <Icon size={13} stroke={1.8} />
          <span className="flex-1 truncate">{label}</span>
          {badge > 0 && <span className="text-[11px]">{badge}</span>}
        </button>
        <Link
          href={addHref}
          title={`Add ${label.toLowerCase()}`}
          aria-label={`Add ${label.toLowerCase()}`}
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-tertiary opacity-0 hover:bg-bg-primary hover:text-ink-primary group-hover:opacity-100"
        >
          <IconPlus size={11} />
        </Link>
      </div>
      {open && (
        <div className="space-y-0.5 pb-0.5 pl-5">
          {items.length === 0 && (
            <p className="px-1.5 py-0.5 text-[11px] text-ink-tertiary">None yet.</p>
          )}
          {items.map((item) => (
            <AssetLink key={item.key} item={item} openTabKeys={openTabKeys} />
          ))}
          {more && more.some((group) => group.items.length > 0) && (
            <MoreGroups groups={more} openTabKeys={openTabKeys} />
          )}
        </div>
      )}
    </div>
  );
}

function AssetLink({
  item,
  openTabKeys,
}: {
  item: AssetItem;
  openTabKeys: Set<string>;
}) {
  return (
    <Link
      href={item.href}
      className={cn(
        "block truncate rounded px-1.5 py-1 text-[12px]",
        openTabKeys.has(item.key)
          ? "font-medium text-brand-500"
          : "text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary",
      )}
    >
      {item.label}
    </Link>
  );
}

/** The "More" node: one collapsed level holding the sub-groups that would
 *  otherwise dominate the tree (AI-generated tables, the archive). Each
 *  sub-group expands on its own. */
function MoreGroups({
  groups,
  openTabKeys,
}: {
  groups: { key: string; label: string; items: AssetItem[] }[];
  openTabKeys: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-[12px] text-ink-tertiary hover:bg-bg-secondary hover:text-ink-secondary"
      >
        {open ? <IconChevronDown size={11} /> : <IconChevronRight size={11} />}
        <span className="flex-1 truncate">More</span>
      </button>
      {open && (
        <div className="space-y-0.5 pl-3">
          {groups
            .filter((group) => group.items.length > 0)
            .map((group) => (
              <MoreGroup key={group.key} group={group} openTabKeys={openTabKeys} />
            ))}
        </div>
      )}
    </div>
  );
}

function MoreGroup({
  group,
  openTabKeys,
}: {
  group: { key: string; label: string; items: AssetItem[] };
  openTabKeys: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-[12px] text-ink-tertiary hover:bg-bg-secondary hover:text-ink-secondary"
      >
        {open ? <IconChevronDown size={11} /> : <IconChevronRight size={11} />}
        <span className="flex-1 truncate">{group.label}</span>
        <span className="text-[11px]">{group.items.length}</span>
      </button>
      {open && (
        <div className="space-y-0.5 pl-3">
          {group.items.map((item) => (
            <AssetLink key={item.key} item={item} openTabKeys={openTabKeys} />
          ))}
        </div>
      )}
    </div>
  );
}
