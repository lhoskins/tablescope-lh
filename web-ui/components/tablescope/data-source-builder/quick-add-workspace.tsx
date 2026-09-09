"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { IconFileText, IconX } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import { listMyDataSources } from "@/lib/api/data-source-builder";
import { BUILDER_QUERY_OPTIONS } from "@/lib/query-options";
import {
  useBuilderStore,
  type ProjectAssignment,
} from "@/lib/stores/data-source-builder-store";
import {
  usePendingDocumentsStore,
  type PendingDocument,
} from "@/lib/stores/pending-documents-store";
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

/**
 * One staged item. Every file gets this same card whatever it is -- the badge
 * says what it became, the rows are the same rows, and a row with nothing
 * behind it is simply left out. Documents used to be described in a different
 * shape from data sources, which made two kinds of thing out of what is really
 * one list of "stuff I just added".
 */
interface StagedCardModel {
  name: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  badge: { label: string; tone: "brand" | "ai" };
  /** Rows are rendered in order; entries with an empty value are dropped. */
  rows: [string, string | null][];
  removeLabel: string;
}

function formatBytes(bytes: number): string | null {
  if (!bytes || bytes <= 0) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function StagedCard({
  model,
  onRemove,
}: {
  model: StagedCardModel;
  onRemove: () => void;
}) {
  const Icon = model.icon;
  const rows = model.rows.filter(([, value]) => value);
  return (
    <div className="relative flex flex-col rounded-xl border border-line-tertiary bg-bg-primary p-3.5">
      <button
        type="button"
        onClick={onRemove}
        aria-label={model.removeLabel}
        className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary hover:text-danger"
      >
        <IconX size={13} />
      </button>
      <div className="flex items-start gap-2 pr-5">
        <Icon size={16} className="mt-0.5 shrink-0 text-brand-600" />
        <span className="min-w-0 flex-1 break-words text-[13px] font-medium text-ink-primary">
          {model.name}
        </span>
      </div>
      <div className="mt-2">
        <Badge tone={model.badge.tone}>{model.badge.label}</Badge>
      </div>
      <dl className="mt-2.5 space-y-1 text-caption text-ink-tertiary">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-2">
            <dt>{label}</dt>
            <dd
              className="min-w-0 truncate text-ink-secondary"
              title={value ?? undefined}
            >
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function sourceCardModel(item: FlatItem): StagedCardModel {
  return {
    name: item.name,
    icon: connectorIcon(item.sourceType),
    badge: { label: "Data source", tone: "brand" },
    rows: [
      ["Type", item.typeLabel],
      ["Columns", item.columns > 0 ? String(item.columns) : null],
      ["Size", item.sizeOrStatus !== "—" ? item.sizeOrStatus : null],
      [item.isFile ? "Staged as" : "Source", item.sourceLabel],
    ],
    removeLabel: `Remove ${item.name}`,
  };
}

function documentCardModel(doc: PendingDocument): StagedCardModel {
  return {
    name: doc.fileName,
    icon: IconFileText,
    badge: { label: "Document", tone: "ai" },
    rows: [
      ["Type", "Document"],
      ["Columns", null],
      ["Size", formatBytes(doc.sizeBytes)],
      ["Staged as", "Added when you pick a project"],
    ],
    removeLabel: `Remove ${doc.fileName}`,
  };
}

/** Everything staged so far this session, as removable thumbnail cards. */
function StagedSourcesGrid() {
  const sources = useBuilderStore((s) => s.sources);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const removeSource = useBuilderStore((s) => s.removeSource);
  const updateTableState = useBuilderStore((s) => s.updateTableState);
  const unmarkCreated = useBuilderStore((s) => s.unmarkCreated);

  const items = flattenCreated(sources, createdKeys);
  const pendingDocuments = usePendingDocumentsStore((s) => s.documents);
  const removeDocument = usePendingDocumentsStore((s) => s.remove);

  const remove = (item: FlatItem) => {
    if (item.isFile) {
      removeSource(item.sourceId);
      return;
    }
    const tableName = item.key.slice(item.sourceId.length + 2);
    updateTableState(item.sourceId, tableName, "unselected");
    unmarkCreated(item.key);
  };

  if (items.length === 0 && pendingDocuments.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-secondary px-4 py-10 text-center text-small text-ink-tertiary">
        Nothing staged yet — add a file, link, database, or network share above.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {items.map((item) => (
        <StagedCard
          key={item.key}
          model={sourceCardModel(item)}
          onRemove={() => remove(item)}
        />
      ))}
      {pendingDocuments.map((doc) => (
        <StagedCard
          key={doc.id}
          model={documentCardModel(doc)}
          onRemove={() => removeDocument(doc.id)}
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
  initialSourceTab,
  footer,
  heightClass = "h-[calc(100vh-7rem)]",
}: {
  tenantName: string;
  /** Omitted when opened from Home, where no project has been chosen yet.
   *  Everything below tolerates that: uploads, URL import, database and
   *  network panels all send project_id only when they have one. The one
   *  exception is a document (PDF/DOCX) upload, which the dropzone refuses
   *  with an explanatory message because its route is project-scoped. */
  projectId?: string;
  /** Which method card starts selected. Home's "Data Sources" tile deep-links
   *  to "database" the way the old ?intent=database shim did. */
  initialSourceTab?: SourceTab;
  /** Replaces the default "Add to Project" button. Home passes its own pair
   *  ("Assign to Projects" / "Start New Project") since there is no single
   *  project to add to. */
  footer?: React.ReactNode;
  /** Height of the shell. The default fills the viewport, which pins the
   *  footer to the bottom of the screen -- right inside a project, where the
   *  staged list can be long. Home passes "" so the shell sizes to its
   *  content and the buttons sit directly beneath the staged cards. */
  heightClass?: string;
}) {
  const ensureTenant = useBuilderStore((s) => s.ensureTenant);
  const syncExisting = useBuilderStore((s) => s.syncExisting);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const sources = useBuilderStore((s) => s.sources);
  const projects = useBuilderStore((s) => s.projects);
  const setProjects = useBuilderStore((s) => s.setProjects);
  const toggleProject = useBuilderStore((s) => s.toggleProject);
  const getPendingChanges = useBuilderStore((s) => s.getPendingChanges);

  const [sourceTab, setSourceTab] = useState<SourceTab>(initialSourceTab ?? "upload");
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
    if (autoToggled.current || !projectId) return;
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

  const numericProjectId = projectId ? Number(projectId) : undefined;

  return (
    <div className={`flex flex-col ${heightClass}`}>
      <div className="mt-1 flex shrink-0 items-start justify-between gap-4">
        <SourceMethodTabs activeTab={sourceTab} onChange={setSourceTab} />
        {/* "Also add to" presumes a project this is already being added to.
            Opened from Home there isn't one, and the footer's "Add to
            Existing Project" covers the same ground without the ambiguity. */}
        {projectId && (
          <div className="relative shrink-0">
            <Button variant="secondary" onClick={() => setOptionsOpen((o) => !o)}>
              Options
            </Button>
            {optionsOpen && (
              <ProjectsOptionsPanel onClose={() => setOptionsOpen(false)} />
            )}
          </div>
        )}
      </div>

      <div
        className={`space-y-5 py-4 ${heightClass ? "min-h-0 flex-1 overflow-y-auto" : ""}`}
      >
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

      <div className="flex shrink-0 items-center justify-end gap-3 border-t border-line-tertiary pt-4">
        {footer ?? (
          <Button
            variant="primary"
            disabled={!canAdd}
            onClick={() => setConfirmOpen(true)}
          >
            Add to Project
          </Button>
        )}
      </div>

      <ConfirmationModal
        open={confirmOpen}
        tenantName={tenantName}
        onClose={() => setConfirmOpen(false)}
      />
    </div>
  );
}
