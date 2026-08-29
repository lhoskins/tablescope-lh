"use client";

import { useParams } from "next/navigation";
import { ProjectChatsScreen } from "@/components/tablescope/project/project-chats-screen";

export default function ProjectChatsPage() {
  const params = useParams<{ id: string }>();
  return <ProjectChatsScreen projectId={params.id} />;
}
