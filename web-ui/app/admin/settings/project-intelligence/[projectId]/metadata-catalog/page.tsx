"use client";

import { MetadataCatalogPanel } from "@/components/tablescope/project/metadata-catalog-screen";
import { ProjectIntelligenceHeader } from "@/components/tablescope/settings/project-intelligence-header";
import { useProjectIntelligence } from "@/components/tablescope/settings/project-intelligence-context";

export default function MetadataCatalogSettingsPage() {
  const { project, projectId, isInvalid } = useProjectIntelligence();

  if (isInvalid || !project) {
    return (
      <ProjectIntelligenceHeader
        title="Metadata Catalog"
        section="metadata-catalog"
      />
    );
  }

  return (
    <>
      <ProjectIntelligenceHeader
        title="Metadata Catalog"
        section="metadata-catalog"
      />
      <MetadataCatalogPanel projectId={projectId!} />
    </>
  );
}
