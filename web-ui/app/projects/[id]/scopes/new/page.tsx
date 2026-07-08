"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ProjectShell } from "@/components/tablescope/project-shell";
import { scopesApi } from "@/lib/api/scopes";

export default function NewScopePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);
  const started = useRef(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const set = await scopesApi.createScopeSet(projectId, {
          name: "Untitled Scope",
          type: "manual",
        });
        router.replace(`/projects/${projectId}/scopes/${set.id}/map`);
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, [projectId, router]);

  return (
    <ProjectShell
      projectId={params.id}
      activeNav="project-scopes"
      breadcrumbLabel="New Scope"
    >
      {error ? (
        <p className="text-[13px] text-danger">{error}</p>
      ) : (
        <p className="text-[13px] text-ink-tertiary">Creating scope…</p>
      )}
    </ProjectShell>
  );
}
