"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import type { ProjectSummary } from "@/lib/ui/types";
import { useProjectIntelligenceSelection } from "./use-project-intelligence-selection";

export type ProjectIntelligenceSection =
  | "graph-lifecycle"
  | "metadata-catalog"
  | "reference-library"
  | "audit-log";

interface ProjectIntelligenceContextValue {
  routeProjectId: string;
  /** The project ID after validation; null when the route param is not accessible. */
  projectId: string | null;
  project: ProjectSummary | null;
  projects: ProjectSummary[];
  isLoading: boolean;
  isInvalid: boolean;
  setProjectId: (projectId: string, section?: ProjectIntelligenceSection) => void;
}

const ProjectIntelligenceContext = createContext<
  ProjectIntelligenceContextValue | undefined
>(undefined);

function getHref(section: ProjectIntelligenceSection, projectId: string) {
  return `/admin/settings/project-intelligence/${projectId}/${section}`;
}

export function ProjectIntelligenceProvider({
  routeProjectId,
  children,
}: {
  routeProjectId: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const { data: summaries, isLoading } = useProjectSummaries();
  const { setSelectedProjectId } = useProjectIntelligenceSelection();

  const accessibleMap = useMemo(
    () => new Map((summaries ?? []).map((p) => [p.id, p])),
    [summaries],
  );

  const project = accessibleMap.get(routeProjectId) ?? null;
  const isInvalid = !isLoading && !project;

  const setProjectId = useCallback(
    (nextProjectId: string, section: ProjectIntelligenceSection = "graph-lifecycle") => {
      setSelectedProjectId(nextProjectId);
      router.push(getHref(section, nextProjectId));
    },
    [router, setSelectedProjectId],
  );

  const value = useMemo(
    () => ({
      routeProjectId,
      projectId: project ? routeProjectId : null,
      project,
      projects: summaries ?? [],
      isLoading,
      isInvalid,
      setProjectId,
    }),
    [routeProjectId, project, summaries, isLoading, isInvalid, setProjectId],
  );

  return (
    <ProjectIntelligenceContext.Provider value={value}>
      {children}
    </ProjectIntelligenceContext.Provider>
  );
}

export function useProjectIntelligence(): ProjectIntelligenceContextValue {
  const ctx = useContext(ProjectIntelligenceContext);
  if (!ctx) {
    throw new Error(
      "useProjectIntelligence must be used inside a ProjectIntelligenceProvider",
    );
  }
  return ctx;
}
