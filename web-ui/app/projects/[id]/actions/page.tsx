import { ProjectActionsList } from "@/components/tablescope/project-actions/project-actions-list";

export default function ProjectActionsPage({ params }: { params: { id: string } }) {
  return <ProjectActionsList projectId={params.id} />;
}
