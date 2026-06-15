"use client";

import { useParams } from "next/navigation";
import { RelationshipMapScreen } from "@/components/tablescope/project/relationship-map-screen";

export default function ProjectRelationshipMapPage() {
  const params = useParams<{ id: string }>();
  return <RelationshipMapScreen projectId={params.id} />;
}
