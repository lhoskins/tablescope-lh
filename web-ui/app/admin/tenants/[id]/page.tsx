"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { ToastViewport, useToasts } from "@/components/ui/toast";

type VDBInfo = {
  vdb_id: string;
  vdb_name: string;
  health_status: string;
  location: string;
  is_active: boolean;
  last_health_check: string | null;
};

type TenantUser = {
  id: number;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string | null;
  vdb: VDBInfo | null;
};

type SharedVDB = {
  id: number;
  vdb_id: string;
  vdb_name: string;
  health_status: string;
  location: string;
  is_active: boolean;
  last_health_check: string | null;
};

type TenantDetails = {
  tenant: {
    id: number;
    slug: string;
    name: string;
    is_active: boolean;
    created_at: string;
  };
  users: TenantUser[];
  shared_vdbs: SharedVDB[];
};

type TenantReprocessResponse = {
  tenant_id: number;
  status: string;
  total_projects: number;
  projects_queued: number;
  projects_skipped: number;
  job_ids: string[];
  force: boolean;
};

function HealthBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    deployed: "bg-emerald-50 text-emerald-700",
    active: "bg-emerald-50 text-emerald-700",
    inactive: "bg-red-50 text-red-700",
    unknown: "bg-yellow-50 text-yellow-700",
  };
  const cls = colors[status] ?? colors.unknown;
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}

export default function TenantDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { toasts, push, dismiss } = useToasts();
  const [forceReprocess, setForceReprocess] = useState(true);
  const tenantId = Number(params.id);

  const reprocessMutation = useMutation({
    mutationFn: () =>
      apiClient.post<TenantReprocessResponse>(
        `/api/tenants/${tenantId}/reprocess-documents?force=${forceReprocess ? "true" : "false"}`,
        {},
      ),
    onSuccess: (data) => {
      push(
        `Queued ${data.projects_queued} project reprocess(s)${data.projects_skipped > 0 ? `, ${data.projects_skipped} already running` : ""}`,
        "success",
      );
    },
    onError: (err: unknown) => {
      push(err instanceof Error ? err.message : "Failed to queue tenant reprocess", "error");
    },
  });

  const detailsQuery = useQuery<TenantDetails>({
    queryKey: ["tenant-details", tenantId],
    queryFn: () => apiClient.get<TenantDetails>(`/api/tenants/${tenantId}/details`),
    enabled: !isNaN(tenantId),
  });

  if (detailsQuery.isLoading) return <p>Loading tenant details...</p>;
  if (detailsQuery.error) return <p className="text-red-600">{(detailsQuery.error as Error).message}</p>;
  if (!detailsQuery.data) return null;

  const { tenant, users, shared_vdbs } = detailsQuery.data;

  return (
    <section>
      <header className="mb-6">
        <button
          onClick={() => router.push("/admin/tenants")}
          className="mb-2 text-sm text-brand hover:text-brand/80"
        >
          &larr; Back to Tenants
        </button>
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold text-slate-900">{tenant.name}</h1>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-600">
            {tenant.slug}
          </span>
          {tenant.is_active ? (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">Active</span>
          ) : (
            <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">Inactive</span>
          )}
        </div>
        <p className="mt-1 text-sm text-slate-500">
          Login URL: <a href={`/${tenant.slug}/login`} className="text-brand underline" target="_blank" rel="noopener noreferrer">/{tenant.slug}/login</a>
        </p>
        <div className="mt-4 flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={forceReprocess}
              onChange={(e) => setForceReprocess(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-slate-300 text-brand focus:ring-brand"
            />
            Force reprocess unchanged files
          </label>
          <button
            type="button"
            onClick={() => reprocessMutation.mutate()}
            disabled={reprocessMutation.isPending}
            className="rounded-md bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
          >
            {reprocessMutation.isPending ? "Queueing..." : "Reprocess all tenant documents"}
          </button>
        </div>
      </header>

      {/* Users with VDB info */}
      <div className="mb-8">
        <h2 className="mb-3 text-lg font-medium text-slate-900">
          Users ({users.length})
        </h2>
        {users.length === 0 ? (
          <p className="text-sm text-slate-500">No users in this tenant.</p>
        ) : (
          <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">User</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Role</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">VDB Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">VDB Health</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">VDB Location</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {users.map((u) => (
                  <tr key={u.id}>
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium text-slate-900">{u.email}</div>
                      {u.display_name && (
                        <div className="text-xs text-slate-500">{u.display_name}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-700">{u.role}</td>
                    <td className="px-4 py-3">
                      {u.is_active ? (
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">Active</span>
                      ) : (
                        <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">Inactive</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm font-mono text-slate-700">
                      {u.vdb ? u.vdb.vdb_name : <span className="text-slate-400">None</span>}
                    </td>
                    <td className="px-4 py-3">
                      {u.vdb ? <HealthBadge status={u.vdb.health_status} /> : <span className="text-xs text-slate-400">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-slate-500 max-w-xs truncate" title={u.vdb?.location}>
                      {u.vdb ? u.vdb.location : <span className="text-slate-400">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Shared VDBs */}
      <div>
        <h2 className="mb-3 text-lg font-medium text-slate-900">
          Shared VDBs ({shared_vdbs.length})
        </h2>
        {shared_vdbs.length === 0 ? (
          <p className="text-sm text-slate-500">No shared VDBs for this tenant.</p>
        ) : (
          <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">VDB Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Health</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Location</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Last Check</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {shared_vdbs.map((sv) => (
                  <tr key={sv.id}>
                    <td className="px-4 py-3 text-sm font-mono text-slate-900">{sv.vdb_name}</td>
                    <td className="px-4 py-3"><HealthBadge status={sv.health_status} /></td>
                    <td className="px-4 py-3">
                      {sv.is_active ? (
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">Active</span>
                      ) : (
                        <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">Inactive</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-slate-500 max-w-xs truncate" title={sv.location}>
                      {sv.location}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-500">
                      {sv.last_health_check ? new Date(sv.last_health_check).toLocaleString() : "Never"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </section>
  );
}
