"use client";

import { useEffect, useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { IconCheck, IconFolderPlus, IconSearch } from "@tabler/icons-react";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import { accentFor } from "@/lib/ui/color";
import {
  listProjectDataSources,
  type ProjectDataSourceRow,
} from "@/lib/api/data-source-builder";
import { BUILDER_QUERY_OPTIONS } from "@/lib/query-options";
import {
  useBuilderStore,
  type ExistingProjectSource,
  type ProjectAssignment,
} from "@/lib/stores/data-source-builder-store";
import { flattenCreated, type FlatItem } from "./flatten";
import { connectorIcon } from "./util";

/** Same mapping the wizard's ProjectCard uses -- see project-card.tsx:27. */
function rowToExisting(row: ProjectDataSourceRow): ExistingProjectSource {
  const isDb = row.id != null && row.dbType != null;
  return {
    sourceKey: isDb ? `db:${row.id}` : `file:${row.viewName}`,
    kind: isDb ? "db" : "file",
    viewName: row.viewName,
    backendId: row.id,
    name: row.fileName,
    tableCount: 1,
    aiOn: !!row.aiMetadata && Object.keys(row.aiMetadata).length > 0,
  };
}

function Check({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden
      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
        on
          ? "border-brand-500 bg-brand-500 text-white"
          : "border-line-secondary bg-bg-primary"
      }`}
    >
      {on && <IconCheck size={11} stroke={3} />}
    </span>
  );
}

/**
 * Assigning staged data to projects, from Home.
 *
 * The wizard's step 2 (`available-sources.tsx` + `projects-column.tsx` +
 * `project-card.tsx`) does this already and stays exactly as it is -- it is
 * the finished path and people may depend on its removal controls. But it
 * also expands each project to list what is *already* in it, with per-row
 * Assigned/Remove buttons, which is project management appearing in the
 * middle of an assign task. Arriving from Home the user has just uploaded
 * something and wants one question answered: which project does this go in.
 *
 * So this is the same operation with the management stripped out. It drives
 * the identical store contracts -- `updateTableState` for the selection,
 * `toggleProject` for the targets, `getPendingChanges` read by the same
 * ConfirmationModal -- so the two paths cannot drift in behaviour, only in
 * how much they show.
 *
 * It also quietly fetches each toggled project's current sources and feeds
 * them to `setProjectExisting`. Nothing renders them; they exist because
 * `getPendingChanges` dedupes against that list, so without the fetch a
 * source already in the project would be queued for re-adding.
 */
export function HomeAssignPanel({
  onNewProject,
}: {
  onNewProject: () => void;
}) {
  const sources = useBuilderStore((s) => s.sources);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const projects = useBuilderStore((s) => s.projects);
  const updateTableState = useBuilderStore((s) => s.updateTableState);
  const toggleProject = useBuilderStore((s) => s.toggleProject);
  const setProjects = useBuilderStore((s) => s.setProjects);
  const setProjectExisting = useBuilderStore((s) => s.setProjectExisting);

  const { data: summaries } = useProjectSummaries();
  useEffect(() => {
    if (!summaries) return;
    setProjects(
      summaries.map((p): ProjectAssignment => {
        const prev = useBuilderStore
          .getState()
          .projects.find((x) => x.projectId === p.id);
        return {
          projectId: p.id,
          projectName: p.name,
          color: p.accent ?? accentFor(p.id),
          isToggled: prev?.isToggled ?? false,
          existingSources: prev?.existingSources ?? [],
          sourcesToRemove: prev?.sourcesToRemove ?? [],
          scopeIds: prev?.scopeIds ?? [],
        };
      }),
    );
  }, [summaries, setProjects]);

  const items = flattenCreated(sources, createdKeys);
  const selectedItems = items.filter((i) => i.selected);
  const toggledIds = useMemo(
    () => projects.filter((p) => p.isToggled).map((p) => p.projectId),
    [projects],
  );

  // Invisible: only here so getPendingChanges can dedupe (see the doc above).
  const existingQueries = useQueries({
    queries: toggledIds.map((projectId) => ({
      ...BUILDER_QUERY_OPTIONS,
      queryKey: ["builder", "project-datasources", projectId],
      queryFn: () => listProjectDataSources(projectId),
    })),
  });
  const existingSignature = existingQueries
    .map((q) => (q.data ? q.data.length : -1))
    .join(",");
  useEffect(() => {
    toggledIds.forEach((projectId, index) => {
      const rows = existingQueries[index]?.data;
      if (rows) setProjectExisting(projectId, rows.map(rowToExisting));
    });
    // existingSignature stands in for the query results, which are new array
    // identities on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingSignature, toggledIds.join(","), setProjectExisting]);

  const setItem = (item: FlatItem, selected: boolean) => {
    const tableName = item.isFile
      ? (sources.find((s) => s.id === item.sourceId)?.tables[0]?.tableName ?? "")
      : item.key.slice(item.sourceId.length + 2);
    updateTableState(
      item.sourceId,
      tableName,
      selected ? "adding" : "unselected",
    );
  };

  return (
    <div className="mx-auto w-full max-w-2xl space-y-7 py-2">
      <section>
        <h3 className="text-h3 text-ink-primary">
          Data to assign{" "}
          <span className="font-normal text-ink-tertiary">
            ({selectedItems.length} of {items.length})
          </span>
        </h3>
        {items.length === 0 ? (
          <p className="mt-2 text-small text-ink-tertiary">
            Nothing staged yet — add a file, link, database or network share
            first.
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {items.map((item) => {
              const Icon = connectorIcon(item.sourceType);
              return (
                <li key={item.key}>
                  <button
                    type="button"
                    onClick={() => setItem(item, !item.selected)}
                    aria-pressed={item.selected}
                    className="flex w-full items-center gap-2.5 rounded-lg border border-line-tertiary bg-bg-primary px-3 py-2 text-left hover:border-line-secondary"
                  >
                    <Check on={item.selected} />
                    <Icon size={15} className="shrink-0 text-ink-tertiary" />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink-primary">
                      {item.name}
                    </span>
                    <span className="shrink-0 text-caption text-ink-tertiary">
                      {item.typeLabel}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section>
        <h3 className="text-h3 text-ink-primary">Add to</h3>
        <p className="mt-0.5 text-small text-ink-tertiary">
          Pick one or more projects. You can change this later from the
          project&apos;s Data Sources.
        </p>
        <ul className="mt-2 space-y-1">
          {projects.map((project) => (
            <li key={project.projectId}>
              <button
                type="button"
                onClick={() => toggleProject(project.projectId)}
                aria-pressed={project.isToggled}
                className={`flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left ${
                  project.isToggled
                    ? "border-brand-500 bg-brand-50"
                    : "border-line-tertiary bg-bg-primary hover:border-line-secondary"
                }`}
              >
                <Check on={project.isToggled} />
                <span
                  aria-hidden
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: project.color }}
                />
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink-primary">
                  {project.projectName}
                </span>
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              onClick={onNewProject}
              className="flex w-full items-center gap-2.5 rounded-lg border border-dashed border-line-secondary px-3 py-2 text-left text-[13px] text-ink-secondary hover:border-brand-500 hover:text-brand-700"
            >
              <IconFolderPlus size={15} className="shrink-0" />
              New project
            </button>
          </li>
        </ul>
        {projects.length === 0 && (
          <p className="mt-2 flex items-center gap-1.5 text-small text-ink-tertiary">
            <IconSearch size={13} /> No projects yet — create one above.
          </p>
        )}
      </section>
    </div>
  );
}
