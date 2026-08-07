"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

export default function ProjectDatabaseConnectorsPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const router = useRouter();

  useEffect(() => {
    router.replace(`/projects/${projectId}/data-source-builder?sourceTab=database`);
  }, [projectId, router]);

  return null;
}
