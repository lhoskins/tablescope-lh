"use client";

import { useParams } from "next/navigation";
import { KnowledgeGraphLifecycleScreen } from "@/components/tablescope/project/knowledge-graph-lifecycle-screen";

export default function KnowledgeGraphLifecyclePage() {
  const params = useParams<{ id: string }>();
  return <KnowledgeGraphLifecycleScreen projectId={params.id} />;
}
