"use client";

import { KnowledgeGraphLifecyclePanel } from "@/components/tablescope/project/knowledge-graph-lifecycle-screen";
import { ProjectIntelligenceHeader } from "@/components/tablescope/settings/project-intelligence-header";
import { useProjectIntelligence } from "@/components/tablescope/settings/project-intelligence-context";

export default function GraphLifecycleSettingsPage() {
  const { project, projectId, isInvalid } = useProjectIntelligence();

  if (isInvalid || !project) {
    return (
      <ProjectIntelligenceHeader
        title="Graph Lifecycle"
        section="graph-lifecycle"
      />
    );
  }

  return (
    <>
      <ProjectIntelligenceHeader
        title="Graph Lifecycle"
        section="graph-lifecycle"
      />
      <KnowledgeGraphLifecyclePanel projectId={projectId!} />
    </>
  );
}
