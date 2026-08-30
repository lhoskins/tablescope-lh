"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconArrowLeft,
  IconArrowRight,
  IconCheck,
  IconDatabase,
  IconFolderShare,
} from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { NewProjectDialog } from "@/components/tablescope/project/new-project-dialog";
import { listMyDataSources } from "@/lib/api/data-source-builder";
import { BUILDER_QUERY_OPTIONS } from "@/lib/query-options";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { buildExistingSources } from "./existing-sources";
import { AvailableSources } from "./available-sources";
import { ConfirmationModal } from "./confirmation-modal";
import { ProjectsColumn } from "./projects-column";
import { AiUploadDropzone } from "./ai-upload-dropzone";
import { UrlImportForm } from "./url-import-form";
import { SourceMethodTabs, type SourceTab } from "./source-method-tabs";
import { DataSourceSelectionSection } from "./data-source-selection-section";
import { ConnectedSourcesSection } from "./connected-sources-section";
import { DatabaseConnectionsPanel } from "./database-connections-panel";
import { NetworkFileConnectionsPanel } from "./network-file-connections-panel";

type Step = 1 | 2;

const STEPS: { n: Step; label: string; icon: typeof IconDatabase }[] = [
  { n: 1, label: "Create Data Sources", icon: IconDatabase },
  { n: 2, label: "Assign Projects", icon: IconFolderShare },
];

function Stepper({ step }: { step: Step }) {
  return (
    <div className="flex items-center gap-3">
      {STEPS.map((s, i) => {
        const active = s.n === step;
        const done = s.n < step;
        const Icon = done ? IconCheck : s.icon;
        return (
          <div key={s.n} className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full text-[12px] font-semibold",
                  active && "bg-brand text-brand-fg",
                  done && "bg-success text-white",
                  !active && !done && "bg-bg-tertiary text-ink-tertiary",
                )}
              >
                {done ? <Icon size={14} /> : s.n}
              </span>
              <span
                className={cn(
                  "text-[13px] font-medium",
                  active ? "text-ink-primary" : "text-ink-tertiary",
                )}
              >
                {s.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <span className="h-px w-8 bg-line-secondary" />
            )}
          </div>
        );
      })}
    </div>
  );
}

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



export function DataSourceBuilderWorkspace({
  tenantName,
  initialProjectId,
  initialSourceTab,
  showConnectedSources = true,
  showDataSourceSelection = true,
}: {
  tenantName: string;
  /** Pre-select this project in Step 2 (arrived from a project-scoped entry point). */
  initialProjectId?: string;
  /** Initial Step 1 tab from ?sourceTab= or legacy ?intent=. */
  initialSourceTab?: SourceTab;
  /**
   * Render the "Connected Sources" section inline in Step 1. Default true
   * (the builder's own standalone/sidebar entry points). Set false when the
   * caller already shows Connected Sources as its own tab right next to
   * this one -- otherwise it renders twice.
   */
  showConnectedSources?: boolean;
  /**
   * Render the "Active Data Sources in this Session / All Data Sources"
   * panel inline in Step 1. Default true. Set false when the caller already
   * shows it elsewhere.
   */
  showDataSourceSelection?: boolean;
}) {
  const queryClient = useQueryClient();
  const ensureTenant = useBuilderStore((s) => s.ensureTenant);
  const syncExisting = useBuilderStore((s) => s.syncExisting);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const getPendingChanges = useBuilderStore((s) => s.getPendingChanges);
  const sources = useBuilderStore((s) => s.sources);
  const projects = useBuilderStore((s) => s.projects);
  const toggleProject = useBuilderStore((s) => s.toggleProject);

  const [step, setStep] = useState<Step>(1);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [sourceTab, setSourceTabState] = useState<SourceTab>(
    initialSourceTab ?? "upload",
  );

  const setSourceTab = (tab: SourceTab) => {
    setSourceTabState(tab);
    const url = new URL(window.location.href);
    url.searchParams.set("sourceTab", tab);
    window.history.replaceState({}, "", url.toString());
  };

  // Keep browser Back/Forward in sync with the active tab.
  useEffect(() => {
    const applyUrlTab = () => {
      const tab = new URLSearchParams(window.location.search).get("sourceTab");
      if (
        tab === "upload" ||
        tab === "url" ||
        tab === "database" ||
        tab === "network"
      ) {
        setSourceTabState(tab);
      }
    };
    window.addEventListener("popstate", applyUrlTab);
    return () => window.removeEventListener("popstate", applyUrlTab);
  }, []);

  const preselected = useRef(false);
  useEffect(() => {
    if (!initialProjectId || preselected.current || step !== 2) return;
    const row = projects.find((p) => p.projectId === initialProjectId);
    if (row && !row.isToggled) {
      preselected.current = true;
      toggleProject(initialProjectId);
    }
  }, [initialProjectId, projects, step, toggleProject]);

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

  const stepHint =
    step === 1
      ? "Step 1 of 2: Create data sources from uploads, URLs, databases, SaaS apps, or network shares."
      : "Step 2 of 2: Assign selected data sources to project(s).";

  const pending = useMemo(
    () => getPendingChanges(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [getPendingChanges, sources, projects],
  );
  const projectsAddingTo = new Set(pending.adding.map((a) => a.projectId)).size;
  const sourcesAdding = pending.adding.reduce(
    (acc, a) => acc + a.tableNames.length,
    0,
  );
  const projectsRemovingFrom = new Set(
    pending.removing.map((r) => r.projectId),
  ).size;
  const canApply = pending.adding.length > 0 || pending.removing.length > 0;

  const numericProjectId = initialProjectId ? Number(initialProjectId) : undefined;

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      <div className="shrink-0 border-b border-line-tertiary pb-3">
        <Stepper step={step} />
        <p className="mt-1.5 text-small text-ink-tertiary">{stepHint}</p>
      </div>

      {step === 1 ? (
        <>
          <div className="mt-4 shrink-0">
            <SourceMethodTabs activeTab={sourceTab} onChange={setSourceTab} />
          </div>

          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto py-4">
            {sourceTab === "upload" && (
              <UploadFilePanel projectId={numericProjectId} />
            )}
            {sourceTab === "url" && <FileUrlPanel />}
            {sourceTab === "database" && (
              <DatabaseConnectionsPanel projectId={initialProjectId} />
            )}
            {sourceTab === "network" && <NetworkFileConnectionsPanel />}

            {showConnectedSources && <ConnectedSourcesSection />}

            {showDataSourceSelection && (
              <DataSourceSelectionSection projectId={initialProjectId} />
            )}
          </div>

          <div className="flex shrink-0 items-center justify-end border-t border-line-tertiary pt-3">
            <Button
              variant="primary"
              disabled={createdKeys.length === 0}
              onClick={() => setStep(2)}
            >
              Next <IconArrowRight size={15} />
            </Button>
          </div>
        </>
      ) : (
        <>
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 overflow-hidden py-4 lg:grid-cols-2">
            <div className="min-h-0 overflow-hidden border-line-tertiary lg:border-r lg:pr-6">
              <AvailableSources />
            </div>
            <ProjectsColumn onNewProject={() => setNewProjectOpen(true)} />
          </div>

          <div className="shrink-0 border-t border-line-tertiary py-2 text-caption text-ink-secondary">
            <span className="font-medium text-brand-700">
              {sourcesAdding} data sources adding to {projectsAddingTo} projects
            </span>{" "}
            ·{" "}
            <span className="font-medium text-danger">
              {pending.removing.length} sources removing from{" "}
              {projectsRemovingFrom} projects
            </span>{" "}
            · Tenant: {tenantName}
          </div>

          <div className="flex shrink-0 items-center justify-between border-t border-line-tertiary pt-3">
            <Button variant="secondary" onClick={() => setStep(1)}>
              <IconArrowLeft size={15} /> Back
            </Button>
            <Button
              variant="primary"
              disabled={!canApply || sources.length === 0}
              onClick={() => setConfirmOpen(true)}
            >
              Apply changes
            </Button>
          </div>
        </>
      )}

      <ConfirmationModal
        open={confirmOpen}
        tenantName={tenantName}
        onClose={() => setConfirmOpen(false)}
      />

      <NewProjectDialog
        open={newProjectOpen}
        redirect={false}
        onClose={() => setNewProjectOpen(false)}
        onCreated={() =>
          queryClient.invalidateQueries({
            queryKey: ["projects", "summaries"],
          })
        }
      />
    </div>
  );
}
