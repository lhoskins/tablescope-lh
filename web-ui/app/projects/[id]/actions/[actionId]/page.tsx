import { ProjectActionDetail } from "@/components/tablescope/project-actions/project-action-detail";

export default function ProjectActionDetailPage({
  params,
}: {
  params: { id: string; actionId: string };
}) {
  return <ProjectActionDetail projectId={params.id} actionId={Number(params.actionId)} />;
}
