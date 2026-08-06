"use client";

import { ProjectReferenceLibraryPanel } from "@/components/tablescope/project/reference-library-screen";
import { ProjectIntelligenceHeader } from "@/components/tablescope/settings/project-intelligence-header";
import { useProjectIntelligence } from "@/components/tablescope/settings/project-intelligence-context";

export default function ProjectReferenceLibrarySettingsPage() {
  const { project, projectId, isInvalid } = useProjectIntelligence();

  if (isInvalid || !project) {
    return (
      <ProjectIntelligenceHeader
        title="Project Reference Library"
        section="reference-library"
      />
    );
  }

  return (
    <>
      <ProjectIntelligenceHeader
        title="Project Reference Library"
        section="reference-library"
      />
      <ProjectReferenceLibraryPanel projectId={projectId!} />
    </>
  );
}
