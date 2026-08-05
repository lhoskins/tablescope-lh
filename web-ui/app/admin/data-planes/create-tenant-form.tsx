"use client";

import type { AppTenant, VpnMode } from "./types";

type CreateTenantFormProps = {
  tenantId: string;
  setTenantId: (value: string) => void;
  tenantName: string;
  setTenantName: (value: string) => void;
  vpnMode: VpnMode;
  setVpnMode: (value: VpnMode) => void;
  cidrs: string;
  setCidrs: (value: string) => void;
  createAppTenant: boolean;
  setCreateAppTenant: (value: boolean) => void;
  adminEmail: string;
  setAdminEmail: (value: string) => void;
  adminPassword: string;
  setAdminPassword: (value: string) => void;
  confirmPassword: string;
  setConfirmPassword: (value: string) => void;
  linkOrgTenantId: number | null;
  setLinkOrgTenantId: (value: number | null) => void;
  error: string | null;
  appTenants: AppTenant[] | undefined;
  isPending: boolean;
  onSubmit: (e: React.FormEvent) => void;
};

export function CreateTenantForm({
  tenantId,
  setTenantId,
  tenantName,
  setTenantName,
  vpnMode,
  setVpnMode,
  cidrs,
  setCidrs,
  createAppTenant,
  setCreateAppTenant,
  adminEmail,
  setAdminEmail,
  adminPassword,
  setAdminPassword,
  confirmPassword,
  setConfirmPassword,
  linkOrgTenantId,
  setLinkOrgTenantId,
  error,
  appTenants,
  isPending,
  onSubmit,
}: CreateTenantFormProps) {
  return (
    <form
      onSubmit={onSubmit}
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
            Stable lowercase slug; drives subnet, container, firewall chain and
            filesystem paths.
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
              firewall). For cloud/SaaS-only data — no customer on-prem access.
              No AWS VPN cost.
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
          Comma- or newline-separated. The tenant firewall allows egress only to
          these ranges.{" "}
          {vpnMode === "none" &&
            "Optional for No-VPN tenants (typically left blank)."}
        </p>
      </div>

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
            {appTenants?.map((t) => (
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
        disabled={isPending || !tenantId || !tenantName}
        className="mt-5 rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
      >
        {isPending ? "Provisioning..." : "Provision Tenant"}
      </button>
    </form>
  );
}
