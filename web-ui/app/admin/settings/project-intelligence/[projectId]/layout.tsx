"use client";

import { useParams } from "next/navigation";
import { type ReactNode } from "react";
import { ProjectIntelligenceProvider } from "@/components/tablescope/settings/project-intelligence-context";

export default function ProjectIntelligenceLayout({
  children,
}: {
  children: ReactNode;
}) {
  const params = useParams<{ projectId: string }>();
  return (
    <ProjectIntelligenceProvider routeProjectId={params.projectId}>
      {children}
    </ProjectIntelligenceProvider>
  );
}
