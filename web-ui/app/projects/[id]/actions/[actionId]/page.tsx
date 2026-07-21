import { use } from "react";
import { ProjectActionDetail } from "@/components/tablescope/project-actions/project-action-detail";

export default function ProjectActionDetailPage({
  params,
}: {
  params: Promise<{ id: string; actionId: string }>;
}) {
  const { id, actionId } = use(params);
  return <ProjectActionDetail projectId={id} actionId={Number(actionId)} />;
}
