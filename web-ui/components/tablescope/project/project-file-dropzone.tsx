"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AiUploadDropzone } from "@/components/tablescope/data-source-builder/ai-upload-dropzone";
import {
  useBuilderStore,
  type ProjectAssignment,
} from "@/lib/stores/data-source-builder-store";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import type { ProjectSummary } from "@/lib/ui/types";

export function ProjectFileDropzone({
  project,
  tenantName,
}: {
  project?: ProjectSummary;
  tenantName: string;
}) {
  const router = useRouter();
  const { data: summaries } = useProjectSummaries();
  const ensureTenant = useBuilderStore((s) => s.ensureTenant);
  const setProjects = useBuilderStore((s) => s.setProjects);

  // Hydrate the persisted builder store for this tenant before any source is
  // added; otherwise sources could be dropped on a stale/out-of-tenant session.
  useEffect(() => {
    if (!tenantName) return;
    void useBuilderStore.persist.rehydrate();
    ensureTenant(tenantName);
  }, [ensureTenant, tenantName]);

  const handleDone = () => {
    if (summaries) {
      const prev = new Map(
        useBuilderStore.getState().projects.map((p) => [p.projectId, p]),
      );
      setProjects(
        summaries.map((p): ProjectAssignment => {
          const existing = prev.get(p.id);
          return {
            projectId: p.id,
            projectName: p.name,
            color: p.accent ?? "#185FA5",
            isToggled:
              (project && p.id === project.id) || existing?.isToggled || false,
            existingSources: existing?.existingSources ?? [],
            sourcesToRemove: existing?.sourcesToRemove ?? [],
            scopeIds: existing?.scopeIds ?? [],
          };
        }),
      );
    } else if (project) {
      setProjects([
        {
          projectId: project.id,
          projectName: project.name,
          color: project.accent ?? "#185FA5",
          isToggled: true,
          existingSources: [],
          sourcesToRemove: [],
          scopeIds: [],
        },
      ]);
    }

    // "Replace the current window" with the Data Source Builder, where the
    // uploaded file is already staged and the current project is selected when
    // one was provided.
    router.push("/data-source-builder");
  };

  return <AiUploadDropzone onUploadsDone={handleDone} />;
}
