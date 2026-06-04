"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { getUserMeta } from "@/lib/auth";

type VpnMode = "none" | "customer_vpn";

type DataPlane = {
  id: number;
  tenant_id: string;
  tenant_name: string;
  vpn_mode: VpnMode;
  status: string;
  docker_subnet_cidr: string;
  teiid_container_ip: string;
  teiid_pg_port: number;
  vdb_host_path: string;
  allowed_onprem_cidrs: string[];
  vpn_status: string | null;
  vpn_connection_id: string | null;
  tenant_vpc_id: string | null;
  last_health_status: string | null;
  org_tenant_id: number | null;
};

type HealthReport = {
  tenant_id: string;
  vpn_status: string;
  teiid_status: string;
  firewall_status: string;
  vdb_path_status: string;
  messages?: Record<string, string>;
};

const STATUS_STYLES: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  provisioning: "bg-amber-100 text-amber-700",
  container_pending: "bg-amber-100 text-amber-700",
  healthy: "bg-green-100 text-green-700",
  applied: "bg-green-100 text-green-700",
  ok: "bg-green-100 text-green-700",
  up: "bg-green-100 text-green-700",
  down: "bg-red-100 text-red-700",
  not_applicable: "bg-slate-100 text-slate-500",
  not_configured: "bg-slate-100 text-slate-500",
  unknown: "bg-slate-100 text-slate-500",
};

function Badge({ value }: { value: string | null }) {
  const v = value ?? "unknown";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[v] ?? "bg-slate-100 text-slate-600"
      }`}
    >
      {v}
    </span>
  );
}

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

  // Bind-existing-data-plane-to-app-tenant modal state.
  const [bindFor, setBindFor] = useState<string | null>(null);
  const [bindCreateNew, setBindCreateNew] = useState(true);
  const [bindSlug, setBindSlug] = useState("");
  const [bindName, setBindName] = useState("");
  const [bindEmail, setBindEmail] = useState("");
  const [bindPassword, setBindPassword] = useState("");
  const [bindOrgId, setBindOrgId] = useState<number | null>(null);
  const [bindError, setBindError] = useState<string | null>(null);

  const planesQuery = useQuery<DataPlane[]>({
    queryKey: ["data-planes"],
    queryFn: () => apiClient.get<DataPlane[]>("/api/tenant-data-planes"),
  });

  type AppTenant = { id: number; slug: string; name: string };
  const appTenantsQuery = useQuery<AppTenant[]>({
    queryKey: ["app-tenants"],
    queryFn: () =>
      apiClient.get<AppTenant[]>("/api/tenant-data-planes/app-tenants"),
    enabled: (showCreate && !createAppTenant) || (bindFor !== null && !bindCreateNew),
  });

  const bindMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, unknown> }) =>
      apiClient.post<DataPlane>(
        `/api/tenant-data-planes/${id}/bind-app-tenant`,
        payload
      ),
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
      apiClient.post<{ note: string }>(
        `/api/tenant-data-planes/${id}/provision-container`,
        {}
      ),
    onSuccess: (resp) => {
      setNote(resp.note);
      queryClient.invalidateQueries({ queryKey: ["data-planes"] });
    },
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
        <form
          onSubmit={handleSubmit}
          className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
        >
          <h2 className="mb-4 text-lg font-medium text-slate-900">
            Provision Tenant Data Plane
          </h2>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Tenant ID
              </label>
              <input
                type="text"
                value={tenantId}
                onChange={(e) =>
                  setTenantId(
                    e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")
                  )
                }
                required
                pattern="^[a-z0-9][a-z0-9-]*$"
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="acme"
              />
              <p className="mt-1 text-xs text-slate-400">
                Stable lowercase slug; drives subnet, container, firewall chain
                and filesystem paths.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Tenant Name
              </label>
              <input
                type="text"
                value={tenantName}
                onChange={(e) => setTenantName(e.target.value)}
                required
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="Acme Corporation"
              />
            </div>
          </div>

          {/* VPN mode selector */}
          <div className="mt-5">
            <label className="block text-sm font-medium text-slate-700">
              Connectivity Tier
            </label>
            <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">
              <button
                type="button"
                onClick={() => setVpnMode("none")}
                className={`rounded-lg border p-4 text-left transition-colors ${
                  vpnMode === "none"
                    ? "border-brand bg-brand/5 ring-1 ring-brand"
                    : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <span className="block text-sm font-semibold text-slate-900">
                  No VPN
                </span>
                <span className="mt-1 block text-xs text-slate-500">
                  Container-only isolation (own Docker network, VDB, secrets,
                  firewall). For cloud/SaaS-only data — no customer on-prem
                  access. No AWS VPN cost.
                </span>
              </button>
              <button
                type="button"
                onClick={() => setVpnMode("customer_vpn")}
                className={`rounded-lg border p-4 text-left transition-colors ${
                  vpnMode === "customer_vpn"
                    ? "border-brand bg-brand/5 ring-1 ring-brand"
                    : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <span className="block text-sm font-semibold text-slate-900">
                  Customer with VPN
                </span>
                <span className="mt-1 block text-xs text-slate-500">
                  Dedicated VPC + AWS Site-to-Site VPN to the customer&apos;s
                  on-prem network (run Terraform, then attach metadata). Bills
                  ~$36/mo per VPN.
                </span>
              </button>
            </div>
          </div>

          <div className="mt-5">
            <label className="block text-sm font-medium text-slate-700">
              Allowed on-prem CIDRs
              {vpnMode === "customer_vpn" && (
                <span className="text-red-500"> *</span>
              )}
            </label>
            <textarea
              value={cidrs}
              onChange={(e) => setCidrs(e.target.value)}
              rows={2}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
              placeholder="10.10.0.0/16, 10.20.0.0/16"
            />
            <p className="mt-1 text-xs text-slate-400">
              Comma- or newline-separated. The tenant firewall allows egress
              only to these ranges.{" "}
              {vpnMode === "none" &&
                "Optional for No-VPN tenants (typically left blank)."}
            </p>
          </div>

          {/* Application tenant creation */}
          <div className="mt-5">
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                checked={createAppTenant}
                onChange={(e) => setCreateAppTenant(e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
              />
              Also create application tenant (login-ready with admin account)
            </label>
          </div>

          {createAppTenant && (
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Admin Email <span className="text-red-500">*</span>
                </label>
                <input
                  type="email"
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                  required={createAppTenant}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                  placeholder="admin@acme.com"
                />
              </div>
              <div />
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Admin Password <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  value={adminPassword}
                  onChange={(e) => setAdminPassword(e.target.value)}
                  required={createAppTenant}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Confirm Password <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required={createAppTenant}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                />
              </div>
            </div>
          )}

          {!createAppTenant && (
            <div className="mt-4">
              <label className="block text-sm font-medium text-slate-700">
                Link to existing application tenant (optional)
              </label>
              <select
                value={linkOrgTenantId ?? ""}
                onChange={(e) =>
                  setLinkOrgTenantId(
                    e.target.value ? Number(e.target.value) : null
                  )
                }
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
              >
                <option value="">-- none (infra only) --</option>
                {appTenantsQuery.data?.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.slug} — {t.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={createMutation.isPending || !tenantId || !tenantName}
            className="mt-5 rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
          >
            {createMutation.isPending ? "Provisioning..." : "Provision Tenant"}
          </button>
        </form>
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
                      <Badge value={p.status} />
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-slate-600">
                      <div>{p.docker_subnet_cidr}</div>
                      <div className="text-slate-400">{p.teiid_container_ip}</div>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {p.vpn_mode === "customer_vpn" ? (
                        <div>
                          <Badge value={p.vpn_status} />
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
                            teiid <Badge value={h.teiid_status} />
                          </div>
                          <div>
                            fw <Badge value={h.firewall_status} />
                          </div>
                          <div>
                            vdb <Badge value={h.vdb_path_status} />
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <form
            onSubmit={submitBind}
            className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-xl"
          >
            <h2 className="text-lg font-medium text-slate-900">
              Bind app tenant to{" "}
              <span className="font-mono">{bindFor}</span>
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Link this data plane to an application tenant so logins for that
              tenant route to its dedicated Teiid container.
            </p>

            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={() => setBindCreateNew(true)}
                className={`flex-1 rounded-lg border p-3 text-left text-sm ${
                  bindCreateNew
                    ? "border-brand bg-brand/5 ring-1 ring-brand"
                    : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <span className="block font-semibold text-slate-900">
                  Create new app tenant
                </span>
                <span className="text-xs text-slate-500">
                  Slug + root admin login
                </span>
              </button>
              <button
                type="button"
                onClick={() => setBindCreateNew(false)}
                className={`flex-1 rounded-lg border p-3 text-left text-sm ${
                  !bindCreateNew
                    ? "border-brand bg-brand/5 ring-1 ring-brand"
                    : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <span className="block font-semibold text-slate-900">
                  Link existing tenant
                </span>
                <span className="text-xs text-slate-500">
                  Pick an existing org tenant
                </span>
              </button>
            </div>

            {bindCreateNew ? (
              <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-slate-700">
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={bindSlug}
                    onChange={(e) =>
                      setBindSlug(
                        e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")
                      )
                    }
                    className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                    placeholder="acme"
                  />
                  <p className="mt-1 text-xs text-slate-400">
                    Login URL: /{bindSlug || "slug"}/login
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700">
                    Display name
                  </label>
                  <input
                    type="text"
                    value={bindName}
                    onChange={(e) => setBindName(e.target.value)}
                    className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                    placeholder="Acme Corporation"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700">
                    Admin email <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="email"
                    value={bindEmail}
                    onChange={(e) => setBindEmail(e.target.value)}
                    className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                    placeholder="admin@acme.com"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700">
                    Admin password <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="password"
                    value={bindPassword}
                    onChange={(e) => setBindPassword(e.target.value)}
                    className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                    placeholder="••••••••"
                  />
                </div>
              </div>
            ) : (
              <div className="mt-4">
                <label className="block text-sm font-medium text-slate-700">
                  Existing app tenant
                </label>
                <select
                  value={bindOrgId ?? ""}
                  onChange={(e) =>
                    setBindOrgId(e.target.value ? Number(e.target.value) : null)
                  }
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                >
                  <option value="">Select a tenant…</option>
                  {appTenantsQuery.data?.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.slug} — {t.name} (#{t.id})
                    </option>
                  ))}
                </select>
              </div>
            )}

            {bindError && (
              <p className="mt-3 text-sm text-red-600">{bindError}</p>
            )}

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setBindFor(null)}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={bindMutation.isPending}
                className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
              >
                {bindMutation.isPending ? "Binding…" : "Bind"}
              </button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}
