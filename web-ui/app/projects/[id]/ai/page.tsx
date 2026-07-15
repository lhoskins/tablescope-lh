"use client";

import { useParams } from "next/navigation";
import { ProjectConversationScreen } from "@/components/tablescope/conversation/project-conversation-screen";

export default function ProjectAiAssistantPage() {
  const params = useParams<{ id: string }>();
  return <ProjectConversationScreen projectId={params.id} />;
}
