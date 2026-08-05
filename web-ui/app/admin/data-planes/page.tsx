"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { getUserMeta } from "@/lib/auth";
import { StatusBadge } from "./status-badge";
import { CreateTenantForm } from "./create-tenant-form";
import { BindAppTenantModal } from "./bind-app-tenant-modal";
import { DeleteTenantModal } from "./delete-tenant-modal";
import { TeardownModal } from "./teardown-modal";
import type { DataPlane, HealthReport, DeleteResult, VpnMode, AppTenant } from "./types";

export default function DataPlanesPage() {
  const meta = getUserMeta();
  const isSuperAdmin = meta?.is_super_admin ?? false;

  if (!isSuperAdmin) {
    return (
      <section>
        <h1 className="text-2xl font-semibold text-slate-900">Data Planes</h1>
        <p className="mt-2 text-sm text-slate-500">
          Only super-admins can manage tenant data planes.
        </p>
      </section>
    );
  }
  return <SuperAdminView />;
}

function SuperAdminView() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [tenantId, setTenantId] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [vpnMode, setVpnMode] = useState<VpnMode>("none");
  const [cidrs, setCidrs] = useState("");
  const [createAppTenant, setCreateAppTenant] = useState(true);
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [linkOrgTenantId, setLinkOrgTenantId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Record<string, HealthReport>>({});
  const [note, setNote] = useState<string | null>(null);

  const [bindFor, setBindFor] = useState<string | null>(null);
  const [bindCreateNew, setBindCreateNew] = useState(true);
  const [bindSlug, setBindSlug] = useState("");
  const [bindName, setBindName] = useState("");
  const [bindEmail, setBindEmail] = useState("");
  const [bindPassword, setBindPassword] = useState("");
  const [bindOrgId, setBindOrgId] = useState<number | null>(null);
  const [bindError, setBindError] = useState<string | null>(null);

  const [deleteFor, setDeleteFor] = useState<DataPlane | null>(null);
  const [deleteAppTenant, setDeleteAppTenant] = useState(true);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [teardown, setTeardown] = useState<DeleteResult | null>(null);

  const planesQuery = useQuery<DataPlane[]>({
    queryKey: ["data-planes"],
    queryFn: () => apiClient.get<DataPlane[]>("/api/tenant-data-planes"),
  });

  const appTenantsQuery = useQuery<AppTenant[]>({
    queryKey: ["app-tenants"],
    queryFn: () =>
      apiClient.get<AppTenant[]>("/api/tenant-data-planes/app-tenants"),
    enabled: (showCreate && !createAppTenant) || (bindFor !== null && !bindCreateNew),
  });

  const bindMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, unknown> }) =>
      apiClient.post<DataPlane>(`/api/tenant-data-planes/${id}/bind-app-tenant`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["data-planes"] });
      queryClient.invalidateQueries({ queryKey: ["app-tenants"] });
      setBindFor(null);
      setBindSlug("");
      setBindName("");
      setBindEmail("");
      setBindPassword("");
      setBindOrgId(null);
      setBindError(null);
    },
    onError: (err: Error) => setBindError(err.message),
  });

  function submitBind(e: React.FormEvent) {
    e.preventDefault();
    setBindError(null);
    if (!bindFor) return;
    const payload: Record<string, unknown> = {};
    if (bindCreateNew) {
      if (!bindSlug || !bindEmail || !bindPassword) {
        setBindError("Slug, admin email and password are required.");
        return;
      }
      payload.new_tenant_slug = bindSlug;
      payload.new_tenant_name = bindName || bindSlug;
      payload.admin_email = bindEmail;
      payload.admin_password = bindPassword;
    } else {
      if (!bindOrgId) {
        setBindError("Select an existing app tenant to link.");
        return;
      }
      payload.org_tenant_id = bindOrgId;
    }
    bindMutation.mutate({ id: bindFor, payload });
  }

  const createMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiClient.post<DataPlane>("/api/tenant-data-planes", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["data-planes"] });
      setShowCreate(false);
      setTenantId("");
      setTenantName("");
      setVpnMode("none");
      setCidrs("");
      setCreateAppTenant(true);
      setAdminEmail("");
      setAdminPassword("");
      setConfirmPassword("");
      setLinkOrgTenantId(null);
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const healthMutation = useMutation({
    mutationFn: (id: string) =>
      apiClient.post<HealthReport>(`/api/tenant-data-planes/${id}/health`, {}),
    onSuccess: (report) => {
      setHealth((h) => ({ ...h, [report.tenant_id]: report }));
      queryClient.invalidateQueries({ queryKey: ["data-planes"] });
    },
  });

  const provisionMutation = useMutation({
    mutationFn: (id: string) =>
      apiClient.post<{ note: string }>(`/api/tenant-data-planes/${id}/provision-container`, {}),
    onSuccess: (resp) => {
      setNote(resp.note);
      queryClient.invalidateQueries({ queryKey: ["data-planes"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: ({ id, withApp }: { id: string; withApp: boolean }) =>
      apiClient.delete<DeleteResult>(`/api/tenant-data-planes/${id}?delete_app_tenant=${withApp}`),
    onSuccess: (resp) => {
      setDeleteFor(null);
      setDeleteError(null);
      setTeardown(resp);
      queryClient.invalidateQueries({ queryKey: ["data-planes"] });
      queryClient.invalidateQueries({ queryKey: ["app-tenants"] });
    },
    onError: (err: Error) => setDeleteError(err.message),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const list = cidrs
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (vpnMode === "customer_vpn" && list.length === 0) {
      setError("Customer-VPN tenants require at least one on-prem CIDR.");
      return;
    }
    if (createAppTenant) {
      if (!adminEmail || !adminPassword) {
        setError("Admin email and password are required to create the app tenant.");
        return;
      }
      if (adminPassword !== confirmPassword) {
        setError("Passwords do not match.");
        return;
      }
    }
    const payload: Record<string, unknown> = {
      tenant_id: tenantId,
      tenant_name: tenantName,
      vpn_mode: vpnMode,
      allowed_onprem_cidrs: list,
      create_app_tenant: createAppTenant,
    };
    if (createAppTenant) {
      payload.app_tenant_admin_email = adminEmail;
      payload.app_tenant_admin_password = adminPassword;
    } else if (linkOrgTenantId) {
      payload.org_tenant_id = linkOrgTenantId;
    }
    createMutation.mutate(payload);
  }

  return (
    <section>
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            Tenant Data Planes
          </h1>
          <p className="text-sm text-slate-500">
            Provision per-tenant isolation (VPC + Site-to-Site VPN + Teiid
            container + Docker network + VDB + firewall) on the shared EC2 host.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90"
        >
          {showCreate ? "Cancel" : "New Tenant"}
        </button>
      </header>

      {showCreate && (
        <CreateTenantForm
          tenantId={tenantId}
          setTenantId={setTenantId}
          tenantName={tenantName}
          setTenantName={setTenantName}
          vpnMode={vpnMode}
          setVpnMode={setVpnMode}
          cidrs={cidrs}
          setCidrs={setCidrs}
          createAppTenant={createAppTenant}
          setCreateAppTenant={setCreateAppTenant}
          adminEmail={adminEmail}
          setAdminEmail={setAdminEmail}
          adminPassword={adminPassword}
          setAdminPassword={setAdminPassword}
          confirmPassword={confirmPassword}
          setConfirmPassword={setConfirmPassword}
          linkOrgTenantId={linkOrgTenantId}
          setLinkOrgTenantId={setLinkOrgTenantId}
          error={error}
          appTenants={appTenantsQuery.data}
          isPending={createMutation.isPending}
          onSubmit={handleSubmit}
        />
      )}

      {note && (
        <div className="mb-6 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <p className="mb-1 font-medium">Next operator step</p>
          <p className="whitespace-pre-wrap">{note}</p>
          <button
            onClick={() => setNote(null)}
            className="mt-2 text-xs underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {planesQuery.isLoading && <p>Loading data planes...</p>}
      {planesQuery.error && (
        <p className="text-red-600">{(planesQuery.error as Error).message}</p>
      )}

      {planesQuery.data && planesQuery.data.length === 0 && !showCreate && (
        <div className="rounded-lg border-2 border-dashed border-slate-200 p-12 text-center">
          <p className="text-slate-500">No tenant data planes yet.</p>
          <p className="mt-1 text-sm text-slate-400">
            Click &quot;New Tenant&quot; to provision one.
          </p>
        </div>
      )}

      {planesQuery.data && planesQuery.data.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                {[
                  "Tenant",
                  "Tier",
                  "Status",
                  "Subnet / IP",
                  "VPN",
                  "Health",
                  "Actions",
                ].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {planesQuery.data.map((p) => {
                const h = health[p.tenant_id];
                return (
                  <tr key={p.id} className="align-top">
                    <td className="px-4 py-3 text-sm">
                      <div className="font-mono font-medium text-slate-900">
                        {p.tenant_id}
                      </div>
                      <div className="text-xs text-slate-500">
                        {p.tenant_name}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {p.vpn_mode === "customer_vpn" ? (
                        <span className="inline-flex rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
                          Customer VPN
                        </span>
                      ) : (
                        <span className="inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                          No VPN
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <StatusBadge value={p.status} />
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-slate-600">
                      <div>{p.docker_subnet_cidr}</div>
                      <div className="text-slate-400">{p.teiid_container_ip}</div>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {p.vpn_mode === "customer_vpn" ? (
                        <div>
                          <StatusBadge value={p.vpn_status} />
                          {p.vpn_connection_id && (
                            <div className="mt-1 font-mono text-[10px] text-slate-400">
                              {p.vpn_connection_id}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-slate-400">n/a</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {h ? (
                        <div className="space-y-1">
                          <div>
                            teiid <StatusBadge value={h.teiid_status} />
                          </div>
                          <div>
                            fw <StatusBadge value={h.firewall_status} />
                          </div>
                          <div>
                            vdb <StatusBadge value={h.vdb_path_status} />
                          </div>
                        </div>
                      ) : (
                        <span className="text-slate-400">
                          {p.last_health_status ?? "—"}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <div className="flex flex-col gap-1">
                        <button
                          onClick={() => healthMutation.mutate(p.tenant_id)}
                          disabled={
                            healthMutation.isPending &&
                            healthMutation.variables === p.tenant_id
                          }
                          className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
                        >
                          Run health
                        </button>
                        <button
                          onClick={() => provisionMutation.mutate(p.tenant_id)}
                          disabled={
                            provisionMutation.isPending &&
                            provisionMutation.variables === p.tenant_id
                          }
                          className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
                        >
                          Provision container
                        </button>
                        {p.org_tenant_id ? (
                          <span className="inline-flex items-center justify-center rounded bg-green-50 px-2 py-1 text-xs font-medium text-green-700">
                            Bound · org #{p.org_tenant_id}
                          </span>
                        ) : (
                          <button
                            onClick={() => {
                              setBindFor(p.tenant_id);
                              setBindCreateNew(true);
                              setBindSlug(p.tenant_id);
                              setBindName(p.tenant_name);
                              setBindError(null);
                            }}
                            className="rounded border border-brand px-2 py-1 text-xs font-medium text-brand hover:bg-brand/5"
                          >
                            Bind app tenant
                          </button>
                        )}
                        <button
                          onClick={() => {
                            setDeleteFor(p);
                            setDeleteAppTenant(p.org_tenant_id != null);
                            setDeleteError(null);
                          }}
                          className="rounded border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {bindFor && (
        <BindAppTenantModal
          bindFor={bindFor}
          bindCreateNew={bindCreateNew}
          setBindCreateNew={setBindCreateNew}
          bindSlug={bindSlug}
          setBindSlug={setBindSlug}
          bindName={bindName}
          setBindName={setBindName}
          bindEmail={bindEmail}
          setBindEmail={setBindEmail}
          bindPassword={bindPassword}
          setBindPassword={setBindPassword}
          bindOrgId={bindOrgId}
          setBindOrgId={setBindOrgId}
          bindError={bindError}
          appTenants={appTenantsQuery.data}
          isPending={bindMutation.isPending}
          onSubmit={submitBind}
          onCancel={() => setBindFor(null)}
        />
      )}

      {deleteFor && (
        <DeleteTenantModal
          deleteFor={deleteFor}
          deleteAppTenant={deleteAppTenant}
          setDeleteAppTenant={setDeleteAppTenant}
          deleteError={deleteError}
          isPending={deleteMutation.isPending}
          onDelete={() =>
            deleteMutation.mutate({
              id: deleteFor.tenant_id,
              withApp:
                deleteFor.org_tenant_id != null ? deleteAppTenant : false,
            })
          }
          onCancel={() => setDeleteFor(null)}
        />
      )}

      {teardown && (
        <TeardownModal
          teardown={teardown}
          onDone={() => setTeardown(null)}
        />
      )}
    </section>
  );
}
