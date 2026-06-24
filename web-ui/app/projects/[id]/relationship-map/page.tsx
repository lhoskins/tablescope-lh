"use client";

import { useParams } from "next/navigation";
import { KnowledgeGraphScreen } from "@/components/tablescope/project/knowledge-graph-screen";

export default function ProjectRelationshipMapPage() {
  const params = useParams<{ id: string }>();
  return (
    <KnowledgeGraphScreen
      projectId={Number(params.id)}
      breadcrumb={["Intelligence", "Knowledge Graph"]}
    />
  );
}
