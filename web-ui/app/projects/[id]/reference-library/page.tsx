"use client";

import { useParams } from "next/navigation";
import { ReferenceLibraryScreen } from "@/components/tablescope/project/reference-library-screen";

export default function ProjectReferenceLibraryPage() {
  const params = useParams<{ id: string }>();
  return <ReferenceLibraryScreen projectId={params.id} />;
}
