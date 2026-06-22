"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronRight,
  IconPlus,
} from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { cn } from "@/lib/cn";
import {
  useBuilderStore,
  type ExistingProjectSource,
  type ProjectAssignment,
  type SessionSource,
} from "@/lib/stores/data-source-builder-store";
import {
  listProjectDataSources,
  type ProjectDataSourceRow,
} from "@/lib/api/data-source-builder";
import { connectorIcon } from "./util";
import { flattenCreated } from "./flatten";

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

function sessionAddRows(sources: SessionSource[]) {
  return sources
    .map((source) => {
      const tableNames = source.isFileUpload
        ? source.tables.map((t) => t.tableName)
        : source.tables.filter((t) => t.state === "adding").map((t) => t.tableName);
      return { source, tableNames };
    })
    .filter((x) => x.tableNames.length > 0);
}

export function ProjectCard({ project }: { project: ProjectAssignment }) {
  const sources = useBuilderStore((s) => s.sources);
  const toggleProject = useBuilderStore((s) => s.toggleProject);
  const markSourceForRemoval = useBuilderStore((s) => s.markSourceForRemoval);
  const undoRemoval = useBuilderStore((s) => s.undoRemoval);
  const setProjectExisting = useBuilderStore((s) => s.setProjectExisting);
  const updateScope = useBuilderStore((s) => s.updateScope);

  const [confirmToggleOff, setConfirmToggleOff] = useState(false);
  const [addingScope, setAddingScope] = useState(false);
  const [scopeName, setScopeName] = useState("");

  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const adding = useMemo(() => sessionAddRows(sources), [sources]);
  const hasPendingAdds = adding.length > 0;
  const expanded = project.isToggled;
  const selectedCount = useMemo(
    () => flattenCreated(sources, createdKeys).filter((i) => i.selected).length,
    [sources, createdKeys],
  );

  const { data: existingRows } = useQuery({
    queryKey: ["builder", "project-datasources", project.projectId],
    queryFn: () => listProjectDataSources(project.projectId),
    enabled: expanded,
  });

  useEffect(() => {
    if (existingRows) {
      setProjectExisting(project.projectId, existingRows.map(rowToExisting));
    }
  }, [existingRows, project.projectId, setProjectExisting]);

  const removingKeys = project.sourcesToRemove;
  const existingVisible = project.existingSources.filter(
    (s) => !removingKeys.includes(s.sourceKey),
  );
  const removingSources = project.existingSources.filter((s) =>
    removingKeys.includes(s.sourceKey),
  );

  const borderClass =
    removingSources.length > 0
      ? "border-danger"
      : expanded && hasPendingAdds
        ? "border-brand-500"
        : "border-line-tertiary";

  const handleToggle = () => {
    if (expanded && hasPendingAdds) {
      setConfirmToggleOff(true);
    } else {
      toggleProject(project.projectId);
    }
  };

  return (
    <div className={cn("rounded-lg border bg-bg-primary", borderClass)}>
      {/* Header row */}
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={handleToggle}
          className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
        >
          {expanded ? (
            <IconChevronDown size={16} className="shrink-0 text-ink-tertiary" />
          ) : (
            <IconChevronRight size={16} className="shrink-0 text-ink-tertiary" />
          )}
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: project.color }}
          />
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-semibold text-ink-primary">
              {project.projectName}
            </span>
          </span>
        </button>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
            project.isToggled
              ? "bg-brand-100 text-brand-700"
              : "bg-bg-tertiary text-ink-tertiary",
          )}
        >
          {project.isToggled ? selectedCount : 0} selected
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={project.isToggled}
          aria-label={`Assign sources to ${project.projectName}`}
          onClick={handleToggle}
          className={cn(
            "relative h-5 w-9 shrink-0 rounded-full transition-colors",
            project.isToggled ? "bg-brand-500" : "bg-line-secondary",
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform",
              project.isToggled ? "translate-x-4" : "translate-x-0.5",
            )}
          />
        </button>
      </div>

      {expanded && (
        <div className="space-y-3 border-t border-line-tertiary px-4 py-3">
          {/* ADDING */}
          {hasPendingAdds && (
            <div>
              <p className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-brand-700">
                Adding
              </p>
              <div className="space-y-1.5">
                {adding.map(({ source, tableNames }) => {
                  const Icon = connectorIcon(source.sourceType);
                  return (
                    <div
                      key={source.id}
                      className="flex items-center gap-2.5 rounded-md border border-brand-500/40 bg-brand-50/40 px-3 py-2"
                    >
                      <Icon size={15} className="shrink-0 text-brand-700" />
                      <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-brand-700">
                        {source.displayName}
                      </span>
                      <span className="text-caption text-ink-tertiary">
                        {source.isFileUpload
                          ? `1 file · ${source.fileMetadata?.rows ?? 0} rows`
                          : `${tableNames.length} tables · AI on`}
                      </span>
                      <Badge tone="brand">Pending</Badge>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ALREADY IN PROJECT */}
          <div>
            <p className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
              Already in project
            </p>
            {existingVisible.length === 0 ? (
              <p className="text-caption text-ink-tertiary">
                No sources in this project yet.
              </p>
            ) : (
              <div className="space-y-1.5">
                {existingVisible.map((s) => {
                  const Icon = connectorIcon("postgresql");
                  return (
                    <div
                      key={s.sourceKey}
                      className="flex items-center gap-2.5 rounded-md border border-line-tertiary px-3 py-2"
                    >
                      <Icon size={15} className="shrink-0 text-ink-tertiary" />
                      <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-secondary">
                        {s.name}
                      </span>
                      <span className="text-caption text-ink-tertiary">
                        {s.tableCount} tables · AI {s.aiOn ? "on" : "off"}
                      </span>
                      <Badge tone="neutral">Assigned</Badge>
                      <button
                        type="button"
                        onClick={() =>
                          markSourceForRemoval(project.projectId, s.sourceKey)
                        }
                        className="rounded border border-danger/40 px-2 py-0.5 text-[11px] font-medium text-danger hover:bg-danger-bg"
                      >
                        Remove
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* REMOVING */}
          {removingSources.length > 0 && (
            <div>
              <p className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-danger">
                Removing
              </p>
              <div className="space-y-1.5">
                {removingSources.map((s) => (
                  <div
                    key={s.sourceKey}
                    className="flex items-center gap-2.5 rounded-md border border-danger/40 bg-danger-bg/40 px-3 py-2"
                  >
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-danger line-through">
                      {s.name}
                    </span>
                    <Badge tone="danger">Will remove</Badge>
                    <button
                      type="button"
                      onClick={() => undoRemoval(project.projectId, s.sourceKey)}
                      className="rounded border border-line-secondary px-2 py-0.5 text-[11px] font-medium text-ink-secondary hover:bg-bg-secondary"
                    >
                      Undo
                    </button>
                  </div>
                ))}
              </div>
              <p className="mt-1.5 flex items-center gap-1 text-caption text-warning">
                <IconAlertTriangle size={13} />
                Removing these sources may affect queries and dashboards.
              </p>
            </div>
          )}

          {/* SCOPE PILLS */}
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
              Scopes:
            </span>
            {project.scopeIds.map((scope) => (
              <span
                key={scope}
                className="rounded-full bg-brand-500 px-2 py-0.5 text-[11px] font-medium text-white"
              >
                {scope}
              </span>
            ))}
            {addingScope ? (
              <input
                autoFocus
                value={scopeName}
                onChange={(e) => setScopeName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && scopeName.trim()) {
                    updateScope(project.projectId, [
                      ...project.scopeIds,
                      scopeName.trim(),
                    ]);
                    setScopeName("");
                    setAddingScope(false);
                  }
                  if (e.key === "Escape") {
                    setAddingScope(false);
                    setScopeName("");
                  }
                }}
                onBlur={() => {
                  setAddingScope(false);
                  setScopeName("");
                }}
                placeholder="Scope name"
                className="h-6 rounded-full border border-line-secondary px-2 text-[11px] focus:border-brand-500 focus:outline-none"
              />
            ) : (
              <button
                type="button"
                onClick={() => setAddingScope(true)}
                className="flex items-center gap-0.5 rounded-full border border-dashed border-line-secondary px-2 py-0.5 text-[11px] text-ink-secondary hover:border-brand-500 hover:text-brand-700"
              >
                <IconPlus size={11} /> Add scope
              </button>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmToggleOff}
        title="Clear pending additions?"
        message={`Turning off ${project.projectName} will clear the sources queued to add to it.`}
        confirmLabel="Clear"
        onConfirm={() => {
          toggleProject(project.projectId);
          setConfirmToggleOff(false);
        }}
        onCancel={() => setConfirmToggleOff(false)}
      />
    </div>
  );
}
