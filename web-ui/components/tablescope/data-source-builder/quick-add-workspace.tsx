"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import { listMyDataSources } from "@/lib/api/data-source-builder";
import { BUILDER_QUERY_OPTIONS } from "@/lib/query-options";
import {
  useBuilderStore,
  type ProjectAssignment,
} from "@/lib/stores/data-source-builder-store";
import { buildExistingSources } from "./existing-sources";
import { SourceMethodTabs, type SourceTab } from "./source-method-tabs";
import { DatabaseConnectionsPanel } from "./database-connections-panel";
import { NetworkFileConnectionsPanel } from "./network-file-connections-panel";
import { AiUploadDropzone } from "./ai-upload-dropzone";
import { UrlImportForm } from "./url-import-form";
import { ConfirmationModal } from "./confirmation-modal";
import { flattenCreated, type FlatItem } from "./flatten";
import { connectorIcon } from "./util";

function UploadFilePanel({ projectId }: { projectId?: number }) {
  return (
    <div className="rounded-xl border border-line-tertiary p-4">
      <h3 className="text-h3 text-ink-primary">Upload file</h3>
      <p className="mt-0.5 text-small text-ink-tertiary">
        Drag and drop a file or click to browse. Supported structured and
        document formats are classified automatically.
      </p>
      <div className="mt-3">
        <AiUploadDropzone projectId={projectId} />
      </div>
    </div>
  );
}

function FileUrlPanel() {
  return (
    <div className="rounded-xl border border-line-tertiary p-4">
      <h3 className="text-h3 text-ink-primary">Import from URL</h3>
      <p className="mt-0.5 text-small text-ink-tertiary">
        Provide a secure HTTPS URL. The platform fetches, validates, and
        profiles the file.
      </p>
      <div className="mt-3 max-w-xl">
        <UrlImportForm />
      </div>
    </div>
  );
}

function StagedSourceCard({
  item,
  onRemove,
}: {
  item: FlatItem;
  onRemove: () => void;
}) {
  const Icon = connectorIcon(item.sourceType);
  return (
    <div className="relative flex h-28 flex-col justify-between rounded-xl border border-line-tertiary bg-bg-primary p-3.5">
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${item.name}`}
        className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary hover:text-danger"
      >
        <IconX size={13} />
      </button>
      <div className="flex items-center gap-2 pr-5">
        <Icon size={16} className="shrink-0 text-brand-600" />
        <span className="min-w-0 truncate text-[13px] font-medium text-ink-primary">
          {item.name}
        </span>
      </div>
      <span className="truncate text-caption text-ink-tertiary">
        {item.typeLabel}
      </span>
    </div>
  );
}

/** Everything staged so far this session, as removable thumbnail cards. */
function StagedSourcesGrid() {
  const sources = useBuilderStore((s) => s.sources);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const removeSource = useBuilderStore((s) => s.removeSource);
  const updateTableState = useBuilderStore((s) => s.updateTableState);
  const unmarkCreated = useBuilderStore((s) => s.unmarkCreated);

  const items = flattenCreated(sources, createdKeys);

  const remove = (item: FlatItem) => {
    if (item.isFile) {
      removeSource(item.sourceId);
      return;
    }
    const tableName = item.key.slice(item.sourceId.length + 2);
    updateTableState(item.sourceId, tableName, "unselected");
    unmarkCreated(item.key);
  };

  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-secondary px-4 py-10 text-center text-small text-ink-tertiary">
        Nothing staged yet — add a file, link, database, or network share above.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {items.map((item) => (
        <StagedSourceCard
          key={item.key}
          item={item}
          onRemove={() => remove(item)}
        />
      ))}
    </div>
  );
}

/** "Options" popover: also assign the staged sources to other projects. */
function ProjectsOptionsPanel({ onClose }: { onClose: () => void }) {
  const projects = useBuilderStore((s) => s.projects);
  const toggleProject = useBuilderStore((s) => s.toggleProject);

  return (
    <>
      <div className="fixed inset-0 z-10" onClick={onClose} />
      <div className="absolute right-0 top-full z-20 mt-2 w-72 rounded-lg border border-line-tertiary bg-bg-primary p-3 shadow-lg">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
            Also add to
          </p>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary"
          >
            <IconX size={14} />
          </button>
        </div>
        {projects.length === 0 ? (
          <p className="px-1 py-2 text-caption text-ink-tertiary">
            Loading projects…
          </p>
        ) : (
          <div className="max-h-64 space-y-0.5 overflow-y-auto">
            {projects.map((p) => (
              <label
                key={p.projectId}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[13px] hover:bg-bg-secondary"
              >
                <input
                  type="checkbox"
                  checked={p.isToggled}
                  onChange={() => toggleProject(p.projectId)}
                  className="h-4 w-4 rounded border-line-secondary"
                />
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: p.color }}
                />
                <span className="min-w-0 flex-1 truncate text-ink-primary">
                  {p.projectName}
                </span>
              </label>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

/**
 * The streamlined, single-screen way to add data sources from inside a
 * project: drag/drop/connect from any method, see everything staged as
 * thumbnails, then one "Add to Project" auto-assigns it all to the current
 * project. "Options" is the escape hatch for also assigning to other
 * projects, as an inline popover instead of a second screen.
 *
 * This is deliberately a separate component from DataSourceBuilderWorkspace
 * (the original 2-step "Create → Assign Projects" wizard), which keeps
 * working unchanged everywhere else it's used (the project sidebar's Tools
 * entry, and any future standalone entry point).
 */
export function QuickAddDataSourceWorkspace({
  tenantName,
  projectId,
}: {
  tenantName: string;
  projectId: string;
}) {
  const ensureTenant = useBuilderStore((s) => s.ensureTenant);
  const syncExisting = useBuilderStore((s) => s.syncExisting);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const sources = useBuilderStore((s) => s.sources);
  const projects = useBuilderStore((s) => s.projects);
  const setProjects = useBuilderStore((s) => s.setProjects);
  const toggleProject = useBuilderStore((s) => s.toggleProject);
  const getPendingChanges = useBuilderStore((s) => s.getPendingChanges);

  const [sourceTab, setSourceTab] = useState<SourceTab>("upload");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);

  useEffect(() => {
    if (!tenantName) return;
    void useBuilderStore.persist.rehydrate();
    ensureTenant(tenantName);
  }, [ensureTenant, tenantName]);

  const { data: myDataSources } = useQuery({
    ...BUILDER_QUERY_OPTIONS,
    queryKey: ["builder", "my-datasources"],
    queryFn: listMyDataSources,
  });
  useEffect(() => {
    if (myDataSources) syncExisting(buildExistingSources(myDataSources));
  }, [myDataSources, syncExisting]);

  // Populate the project list (needed for both the auto-assign below and the
  // "Options" picker) the same way the original wizard's Step 2 does.
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
          color: p.accent ?? "#185FA5",
          isToggled: prev?.isToggled ?? false,
          existingSources: prev?.existingSources ?? [],
          sourcesToRemove: prev?.sourcesToRemove ?? [],
          scopeIds: prev?.scopeIds ?? [],
        };
      }),
    );
  }, [summaries, setProjects]);

  // Auto-assign to the project we were opened from -- the whole point of
  // entering the builder from inside a project instead of standalone.
  const autoToggled = useRef(false);
  useEffect(() => {
    if (autoToggled.current) return;
    const row = projects.find((p) => p.projectId === projectId);
    if (row && !row.isToggled) {
      autoToggled.current = true;
      toggleProject(projectId);
    }
  }, [projectId, projects, toggleProject]);

  // Gate on the pending change set, not just createdKeys -- createdKeys can
  // be non-empty for a moment before the auto-assign effect above has
  // actually toggled the current project on, which would otherwise let
  // "Add to Project" open the confirm modal with nothing queued to add.
  const pending = useMemo(
    () => getPendingChanges(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [getPendingChanges, sources, projects],
  );
  const canAdd = createdKeys.length > 0 && pending.adding.length > 0;

  const numericProjectId = Number(projectId);

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      <div className="mt-1 flex shrink-0 items-start justify-between gap-4">
        <SourceMethodTabs activeTab={sourceTab} onChange={setSourceTab} />
        <div className="relative shrink-0">
          <Button variant="secondary" onClick={() => setOptionsOpen((o) => !o)}>
            Options
          </Button>
          {optionsOpen && (
            <ProjectsOptionsPanel onClose={() => setOptionsOpen(false)} />
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto py-4">
        {sourceTab === "upload" && (
          <UploadFilePanel projectId={numericProjectId} />
        )}
        {sourceTab === "url" && <FileUrlPanel />}
        {sourceTab === "database" && (
          <DatabaseConnectionsPanel projectId={projectId} />
        )}
        {sourceTab === "network" && <NetworkFileConnectionsPanel />}

        <StagedSourcesGrid />
      </div>

      <div className="flex shrink-0 items-center justify-end border-t border-line-tertiary pt-3">
        <Button
          variant="primary"
          disabled={!canAdd}
          onClick={() => setConfirmOpen(true)}
        >
          Add to Project
        </Button>
      </div>

      <ConfirmationModal
        open={confirmOpen}
        tenantName={tenantName}
        onClose={() => setConfirmOpen(false)}
      />
    </div>
  );
}
