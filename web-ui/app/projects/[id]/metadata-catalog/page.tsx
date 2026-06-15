"use client";

import { useParams } from "next/navigation";
import { MetadataCatalogScreen } from "@/components/tablescope/project/metadata-catalog-screen";

export default function ProjectMetadataCatalogPage() {
  const params = useParams<{ id: string }>();
  return <MetadataCatalogScreen projectId={params.id} />;
}
