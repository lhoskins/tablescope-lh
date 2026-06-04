"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

type Tenant = { id: number; slug: string; name: string };

export function TenantSwitcher() {
  const { data, isLoading } = useQuery<Tenant>({
    queryKey: ["tenant-me"],
    queryFn: () => apiClient.get<Tenant>("/api/tenants/me"),
    retry: false,
  });

  if (isLoading) {
    return <span className="text-sm text-slate-500">…</span>;
  }
  if (!data) {
    return <span className="text-sm text-slate-500">Not signed in</span>;
  }
  return (
    <span className="rounded-md bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700">
      {data.name}
    </span>
  );
}
