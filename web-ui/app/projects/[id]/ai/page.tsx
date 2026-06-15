"use client";

import { useParams } from "next/navigation";
import { AiAssistantScreen } from "@/components/tablescope/project/ai-assistant-screen";

export default function ProjectAiAssistantPage() {
  const params = useParams<{ id: string }>();
  return <AiAssistantScreen projectId={params.id} />;
}
