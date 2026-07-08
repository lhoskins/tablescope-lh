"use client";

import { useParams } from "next/navigation";
import { DocumentsScreen } from "@/components/tablescope/project/documents-screen";

export default function ProjectDocumentDetailPage() {
  const params = useParams<{ id: string; documentId: string }>();
  return (
    <DocumentsScreen projectId={params.id} documentId={params.documentId} />
  );
}
