"use client";

import { useParams } from "next/navigation";
import { WorkspaceScreen } from "@/components/tablescope/project/workspace/workspace-screen";

export default function ProjectWorkspacePage() {
  const params = useParams<{ id: string }>();
  return <WorkspaceScreen projectId={params.id} />;
}
