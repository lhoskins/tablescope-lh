"use client";

import { ProjectAuditLogPanel } from "@/components/tablescope/project/audit-log-screen";
import { ProjectIntelligenceHeader } from "@/components/tablescope/settings/project-intelligence-header";
import { useProjectIntelligence } from "@/components/tablescope/settings/project-intelligence-context";

export default function ProjectAuditLogSettingsPage() {
  const { project, projectId, isInvalid } = useProjectIntelligence();

  if (isInvalid || !project) {
    return (
      <ProjectIntelligenceHeader title="Audit Log" section="audit-log" />
    );
  }

  return (
    <>
      <ProjectIntelligenceHeader title="Audit Log" section="audit-log" />
      <ProjectAuditLogPanel projectId={projectId!} />
    </>
  );
}
