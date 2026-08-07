"use client";

import { Suspense, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";

function DatabaseConnectorsCompatibility() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: projects, isLoading } = useProjectSummaries();

  const requestedProjectId = searchParams.get("projectId");

  const accessibleIds = useMemo(
    () => new Set((projects ?? []).map((p) => p.id)),
    [projects],
  );

  useEffect(() => {
    if (isLoading) return;

    if (requestedProjectId && accessibleIds.has(requestedProjectId)) {
      router.replace(
        `/projects/${requestedProjectId}/data-source-builder?sourceTab=database`,
      );
      return;
    }

    const list = projects ?? [];
    if (list.length === 1) {
      router.replace(`/projects/${list[0].id}/data-source-builder?sourceTab=database`);
      return;
    }

    router.replace(
      `/projects${
        list.length === 0 ? "" : "?notice=Select a project to open the Data Source Builder."
      }`,
    );
  }, [isLoading, projects, accessibleIds, requestedProjectId, router]);

  return null;
}

export default function DatabaseConnectorsCompatibilityPage() {
  return (
    <Suspense fallback={null}>
      <DatabaseConnectorsCompatibility />
    </Suspense>
  );
}
