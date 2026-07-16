"use client";

import { useParams } from "next/navigation";
import { BusinessContextScreen } from "@/components/tablescope/project/business-context-screen";

export default function BusinessContextPage() {
  const params = useParams<{ id: string }>();
  return <BusinessContextScreen projectId={params.id} />;
}
