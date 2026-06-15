"use client";

import { useParams } from "next/navigation";
import { DocumentsScreen } from "@/components/tablescope/project/documents-screen";

export default function ProjectDocumentsPage() {
  const params = useParams<{ id: string }>();
  return <DocumentsScreen projectId={params.id} />;
}
