"use client";

import { useParams } from "next/navigation";
import { AuditLogScreen } from "@/components/tablescope/project/audit-log-screen";

export default function ProjectAuditLogPage() {
  const params = useParams<{ id: string }>();
  return <AuditLogScreen projectId={params.id} />;
}
