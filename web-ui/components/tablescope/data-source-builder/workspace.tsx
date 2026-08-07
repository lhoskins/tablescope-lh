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
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { ActiveSourcesTable } from "./active-sources-table";
import { buildExistingSources } from "./existing-sources";
import { FileAcquisitionPanel } from "./file-acquisition-panel";
import { AvailableSources } from "./available-sources";
import { ConfirmationModal } from "./confirmation-modal";
import { ConnectedDatabases } from "./connected-databases";
import { ConnectedNetworkRepositories } from "./connected-network-repositories";
import { ConnectedSaaS } from "./connected-saas";
import { ProjectsColumn } from "./projects-column";

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

export function DataSourceBuilderWorkspace({
  tenantName,
  initialProjectId,
  intent,
}: {
  tenantName: string;
  /** Pre-select this project in Step 2 (arrived from a project-scoped entry point). */
  initialProjectId?: string;
  /**
   * "upload" hides connector selection so the flow is upload-and-scan only.
   * "database" shows only the connected-databases section.
   */
  intent?: "upload" | "database";
}) {
  const queryClient = useQueryClient();
  const ensureTenant = useBuilderStore((s) => s.ensureTenant);
  const syncExisting = useBuilderStore((s) => s.syncExisting);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const getPendingChanges = useBuilderStore((s) => s.getPendingChanges);
  const sources = useBuilderStore((s) => s.sources);
  // Subscribe to projects so the summary + Apply button recompute when a
  // project is toggled or a new project is created.
  const projects = useBuilderStore((s) => s.projects);
  const toggleProject = useBuilderStore((s) => s.toggleProject);

  const [step, setStep] = useState<Step>(1);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [newProjectOpen, setNewProjectOpen] = useState(false);

  // Pre-select the project we arrived from, once, the first time its row
  // shows up in Step 2 (the project list only populates when ProjectsColumn
  // mounts, so this can't run until the user reaches step 2).
  const preselected = useRef(false);
  useEffect(() => {
    if (!initialProjectId || preselected.current || step !== 2) return;
    const row = projects.find((p) => p.projectId === initialProjectId);
    if (row && !row.isToggled) {
      preselected.current = true;
      toggleProject(initialProjectId);
    }
  }, [initialProjectId, projects, step, toggleProject]);

  // The session persists across refreshes (localStorage); rehydrate after mount
  // (storage is skipped during SSR) then drop it only when the tenant changes.
  useEffect(() => {
    void useBuilderStore.persist.rehydrate();
    ensureTenant(tenantName);
  }, [ensureTenant, tenantName]);

  // Load every data source the caller has already created (irrespective of
  // project) so they show in the Active list after a refresh.
  const { data: myDataSources } = useQuery({
    queryKey: ["builder", "my-datasources"],
    queryFn: listMyDataSources,
  });

  useEffect(() => {
    if (myDataSources) syncExisting(buildExistingSources(myDataSources));
  }, [myDataSources, syncExisting]);

  const stepHint =
    step === 1
      ? intent === "upload"
        ? "Step 1 of 2: Upload a file to create a data source (AI-assisted scan and profiling)."
        : intent === "database"
          ? "Step 1 of 2: Choose a connected database and table to create a data source."
          : "Step 1 of 2: Create data sources from files, connected databases, or SaaS connectors."
      : "Step 2 of 2: Assign selected data sources to project(s).";

  // Recompute whenever sources or projects change (toggles/new project).
  // getPendingChanges reads store state internally, so the linter can't see
  // that sources/projects are real dependencies.
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

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      {/* Stepper header */}
      <div className="shrink-0 border-b border-line-tertiary pb-3">
        <Stepper step={step} />
        <p className="mt-1.5 text-small text-ink-tertiary">{stepHint}</p>
      </div>

      {step === 1 ? (
        <>
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto py-4">
            {intent !== "database" && <FileAcquisitionPanel />}

            {intent === "database" && (
              <div>
                <h3 className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                  Connected Databases
                </h3>
                <ConnectedDatabases projectId={initialProjectId} />
              </div>
            )}

            {intent !== "upload" && intent !== "database" && (
              <>
                <div>
                  <h3 className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                    Connected Databases
                  </h3>
                  <ConnectedDatabases projectId={initialProjectId} />
                </div>

                <div>
                  <h3 className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                    SaaS Connections
                  </h3>
                  <ConnectedSaaS projectId={initialProjectId} />
                </div>

                <div>
                  <h3 className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
                    Network Repositories
                  </h3>
                  <ConnectedNetworkRepositories projectId={initialProjectId} />
                </div>
              </>
            )}

            <ActiveSourcesTable />
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

          {/* Summary strip */}
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
