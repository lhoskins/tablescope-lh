import { use } from "react";
import { ProjectActionsList } from "@/components/tablescope/project-actions/project-actions-list";

export default function ProjectActionsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ProjectActionsList projectId={id} />;
}
