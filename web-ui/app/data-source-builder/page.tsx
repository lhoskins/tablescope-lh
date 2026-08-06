"use client";

import { Suspense } from "react";
import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useProjectSummaries } from "@/lib/ui/use-shell-data";

function DataSourceBuilderCompatibility() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: projects, isLoading } = useProjectSummaries();

  const requestedProjectId = searchParams.get("projectId");
  const intent = searchParams.get("intent");

  const accessibleIds = useMemo(
    () => new Set((projects ?? []).map((p) => p.id)),
    [projects],
  );

  useEffect(() => {
    if (isLoading) return;

    const qs = new URLSearchParams();
    if (intent) qs.set("intent", intent);
    const query = qs.toString() ? `?${qs.toString()}` : "";

    if (requestedProjectId && accessibleIds.has(requestedProjectId)) {
      router.replace(`/projects/${requestedProjectId}/data-source-builder${query}`);
      return;
    }

    const list = projects ?? [];
    if (list.length === 1) {
      router.replace(`/projects/${list[0].id}/data-source-builder${query}`);
      return;
    }

    router.replace(
      `/projects${
        list.length === 0 ? "" : "?notice=Select a project to open Data Source Builder."
      }`,
    );
  }, [isLoading, projects, accessibleIds, requestedProjectId, intent, router]);

  return null;
}

export default function DataSourceBuilderCompatibilityPage() {
  return (
    <Suspense fallback={null}>
      <DataSourceBuilderCompatibility />
    </Suspense>
  );
}
