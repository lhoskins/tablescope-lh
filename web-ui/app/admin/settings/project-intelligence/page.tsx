"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";
import { useProjectIntelligenceSelection } from "@/components/tablescope/settings/use-project-intelligence-selection";

export default function ProjectIntelligenceLandingPage() {
  const router = useRouter();
  const { data: projects, isLoading } = useProjectSummaries();
  const { selectedProjectId } = useProjectIntelligenceSelection();

  useEffect(() => {
    if (isLoading) return;

    const accessible = new Set((projects ?? []).map((p) => p.id));
    const target =
      selectedProjectId && accessible.has(selectedProjectId)
        ? selectedProjectId
        : null;

    if (target) {
      router.replace(`/admin/settings/project-intelligence/${target}/graph-lifecycle`);
    }
    // If there is no valid previously-selected project, stay on this page.
    // The UI below renders a project picker.
  }, [isLoading, projects, selectedProjectId, router]);

  if (isLoading) {
    return (
      <div className="py-10 text-center text-small text-ink-tertiary">
        Loading projects…
      </div>
    );
  }

  const accessibleProjects = projects ?? [];
  if (accessibleProjects.length === 0) {
    return (
      <div className="rounded-lg border border-line-tertiary bg-bg-primary p-6 text-center">
        <h1 className="text-xl font-semibold text-ink-primary">
          Project Intelligence
        </h1>
        <p className="mt-2 text-sm text-ink-tertiary">
          You don&apos;t have access to any projects yet.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-line-tertiary bg-bg-primary p-6">
      <h1 className="text-xl font-semibold text-ink-primary">
        Project Intelligence
      </h1>
      <p className="mt-2 text-sm text-ink-tertiary">
        Select a project to view Graph Lifecycle, Metadata Catalog, Reference
        Library, and Audit Log.
      </p>
      <ul className="mt-4 space-y-1">
        {accessibleProjects.map((p) => (
          <li key={p.id}>
            <a
              href={`/admin/settings/project-intelligence/${p.id}/graph-lifecycle`}
              className="block rounded-md px-3 py-2 text-sm text-ink-secondary hover:bg-bg-secondary hover:text-ink-primary"
            >
              {p.name}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
