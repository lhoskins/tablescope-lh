"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ActionCard, ActionCenter } from "@/components/tablescope/project/action-center";
import { NewProjectDialog } from "@/components/tablescope/project/new-project-dialog";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { usePendingDocumentsStore } from "@/lib/stores/pending-documents-store";
import { apiClient } from "@/lib/api-client";
import { QuickAddDataSourceWorkspace } from "./quick-add-workspace";
import type { SourceTab } from "./source-method-tabs";
import { ConnectedSourcesSection } from "./connected-sources-section";
import { AllDataSourcesPanel } from "./all-data-sources-panel";
import { HomeAssignPanel } from "./home-assign-panel";
import { ConfirmationModal } from "./confirmation-modal";

export type HomeBuilderTab = "builder" | "connected" | "all";

/**
 * The Data Builder, reached from Home rather than from inside a project.
 *
 * Home's "Upload File" and "Data Sources" tiles used to bounce through
 * `app/data-source-builder/page.tsx`, which needs a project to redirect into
 * and dumps the user on `/projects` when they have none or several. That is
 * the wrong shape for the tile: at that point the user has data in hand and
 * no project yet, and being asked to pick one first is exactly the friction
 * the Home screen exists to remove.
 *
 * So this is the same three-tab area a project shows, with the project left
 * out. It is composition, not a reimplementation -- every panel below is the
 * one the project screen renders, and the assignment step is the original
 * wizard's step 2 verbatim. What changes is only what happens at the end:
 * instead of one "Add to Project" button there are two, because there is no
 * project yet to add to.
 */
export function HomeDataBuilder({
  tenantName,
  tab,
  method,
  onTabChange,
}: {
  tenantName: string;
  tab: HomeBuilderTab;
  /** Which method card starts selected on the Data Builder tab. */
  method?: SourceTab;
  onTabChange: (tab: HomeBuilderTab) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const sources = useBuilderStore((s) => s.sources);
  const projects = useBuilderStore((s) => s.projects);
  const createdKeys = useBuilderStore((s) => s.createdKeys);
  const setProjects = useBuilderStore((s) => s.setProjects);
  const getPendingChanges = useBuilderStore((s) => s.getPendingChanges);

  // "assign" is the original wizard's step 2, shown in place of the staging
  // area rather than as a separate route so the staged session -- which lives
  // in the builder store -- is never navigated away from.
  const [assigning, setAssigning] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  // Set when "Start New Project" created the project, so the confirm modal's
  // success can land the user in it.
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null);
  const [docError, setDocError] = useState<string | null>(null);

  const pendingDocuments = usePendingDocumentsStore((s) => s.documents);
  const clearDocuments = usePendingDocumentsStore((s) => s.clear);

  /**
   * Send the documents that were waiting on a project.
   *
   * Data sources go through applyChanges in the confirm modal; documents can't
   * -- their route is /projects/{id}/assets/upload and applyChanges has no
   * concept of them. So they are uploaded here, to the one project, once the
   * id exists. A document belongs in one place, so multi-project assignment
   * sends them to the first project chosen.
   */
  const uploadPendingDocuments = useCallback(
    async (projectId: string) => {
      const docs = usePendingDocumentsStore.getState().documents;
      if (docs.length === 0) return;
      const failed: string[] = [];
      for (const doc of docs) {
        try {
          await apiClient.upload(
            `/api/projects/${projectId}/assets/upload`,
            doc.file,
            { asset_type: "document", visibility: "shared_project" },
          );
        } catch {
          failed.push(doc.fileName);
        }
      }
      clearDocuments();
      setDocError(
        failed.length > 0
          ? `Couldn't add ${failed.join(", ")}. Add ${failed.length === 1 ? "it" : "them"} from the project's Documents.`
          : null,
      );
    },
    [clearDocuments],
  );

  const pending = useMemo(
    () => getPendingChanges(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [getPendingChanges, sources, projects],
  );
  // Documents count as staged: a PDF on its own is a legitimate thing to
  // arrive with, and gating the buttons on data sources alone left the user
  // stuck with no way forward.
  const hasStaged = createdKeys.length > 0 || pendingDocuments.length > 0;
  const onlyDocuments = createdKeys.length === 0 && pendingDocuments.length > 0;
  const canApply = pending.adding.length > 0 || pending.removing.length > 0;

  const firstTargetId = projects.find((p) => p.isToggled)?.projectId ?? null;

  const sourcesAdding = useMemo(
    () => pending.adding.reduce((n, a) => n + a.tableNames.length, 0),
    [pending.adding],
  );
  const projectsAddingTo = useMemo(
    () => new Set(pending.adding.map((a) => a.projectId)).size,
    [pending.adding],
  );

  /**
   * "Start New Project" -- create the project, then queue everything staged
   * into it and open the same confirm modal the manual path uses.
   *
   * The new project has to be toggled on optimistically rather than waiting
   * for the summaries refetch: `getPendingChanges` only emits additions for
   * toggled projects, so applying before the refetch lands would silently
   * assign nothing. `setProjects` preserves existing rows, so this is
   * additive rather than a replacement of the list.
   */
  const onProjectCreated = useCallback(
    (id: number) => {
      const projectId = String(id);
      setCreatedProjectId(projectId);
      void queryClient.invalidateQueries({ queryKey: ["projects", "summaries"] });
      const current = useBuilderStore.getState().projects;
      setProjects([
        ...current.map((p) => ({ ...p, isToggled: false })),
        {
          projectId,
          projectName: "",
          color: "#185FA5",
          isToggled: true,
          existingSources: [],
          sourcesToRemove: [],
          scopeIds: [],
        },
      ]);
      void uploadPendingDocuments(projectId).then(() => {
        // With no data sources there is nothing for the confirm modal to
        // apply, so go straight to the project rather than showing an empty
        // review step.
        if (useBuilderStore.getState().createdKeys.length === 0) {
          router.push(`/projects/${projectId}/workspace`);
          return;
        }
        setConfirmOpen(true);
      });
    },
    [queryClient, router, setProjects, uploadPendingDocuments],
  );

  const onConfirmClose = useCallback(() => {
    setConfirmOpen(false);
    if (createdProjectId) {
      const target = createdProjectId;
      setCreatedProjectId(null);
      router.push(`/projects/${target}/workspace`);
    }
  }, [createdProjectId, router]);

  const footer = (
    <>
      <Button
        variant="secondary"
        size="lg"
        disabled={!hasStaged}
        onClick={() => setAssigning(true)}
      >
        Add to Existing Project
      </Button>
      <Button
        variant="primary"
        size="lg"
        disabled={!hasStaged}
        onClick={() => setNewProjectOpen(true)}
      >
        Start Project
      </Button>
    </>
  );

  return (
    <div className="space-y-4">
      <ActionCenter label="Data Sources views">
        <div className="flex items-stretch gap-2">
          <ActionCard
            lines={["Data Builder"]}
            active={tab === "builder"}
            onClick={() => onTabChange("builder")}
          />
          <ActionCard
            lines={["Connected Sources"]}
            active={tab === "connected"}
            onClick={() => onTabChange("connected")}
          />
          <ActionCard
            lines={["All Data Sources"]}
            active={tab === "all"}
            onClick={() => onTabChange("all")}
          />
        </div>
      </ActionCenter>

      {tab === "builder" && !assigning && (
        <QuickAddDataSourceWorkspace
          tenantName={tenantName}
          initialSourceTab={method}
          footer={footer}
          heightClass=""
        />
      )}

      {tab === "builder" && assigning && (
        <div className="flex h-[calc(100vh-11rem)] flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <HomeAssignPanel onNewProject={() => setNewProjectOpen(true)} />
          </div>
          <div className="mt-3 flex shrink-0 items-center justify-between gap-3 border-t border-line-tertiary pt-3">
            <p className="text-caption text-ink-tertiary">
              {sourcesAdding === 0
                ? "Choose data and a project to continue."
                : `${sourcesAdding} ${sourcesAdding === 1 ? "source" : "sources"} → ${projectsAddingTo} ${projectsAddingTo === 1 ? "project" : "projects"}`}
            </p>
            <div className="flex items-center gap-2">
              <Button variant="secondary" onClick={() => setAssigning(false)}>
                Back
              </Button>
              <Button
                variant="primary"
                size="lg"
                disabled={!canApply && !(onlyDocuments && firstTargetId)}
                onClick={() => {
                  if (firstTargetId) void uploadPendingDocuments(firstTargetId);
                  if (canApply) setConfirmOpen(true);
                  else setAssigning(false);
                }}
              >
                Assign
              </Button>
            </div>
          </div>
        </div>
      )}

      {tab === "connected" && <ConnectedSourcesSection />}
      {tab === "all" && <AllDataSourcesPanel />}

      {docError && (
        <p role="alert" className="text-small text-danger">
          {docError}
        </p>
      )}

      <ConfirmationModal
        open={confirmOpen}
        tenantName={tenantName}
        onClose={onConfirmClose}
      />
      <NewProjectDialog
        open={newProjectOpen}
        redirect={false}
        onClose={() => setNewProjectOpen(false)}
        onCreated={onProjectCreated}
      />
    </div>
  );
}
