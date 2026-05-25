"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { getUserMeta } from "@/lib/auth";

type Tenant = {
  id: number;
  slug: string;
  name: string;
  external_id: string | null;
  is_active: boolean;
  created_at: string;
};

export default function TenantsPage() {
  const meta = getUserMeta();
  const isSuperAdmin = meta?.is_super_admin ?? false;

  return isSuperAdmin ? <SuperAdminView /> : <TenantAdminView />;
}

// ── Super Admin: Full tenant provisioning ───────────────────────────

function SuperAdminView() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [rootEmail, setRootEmail] = useState("");
  const [rootName, setRootName] = useState("");
  const [rootPassword, setRootPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const tenantsQuery = useQuery<Tenant[]>({
    queryKey: ["tenants"],
    queryFn: () => apiClient.get<Tenant[]>("/api/tenants"),
  });

  const createMutation = useMutation({
    mutationFn: (payload: {
      slug: string;
      name: string;
      root_user_email?: string;
      root_user_name?: string;
      root_user_password?: string;
    }) => apiClient.post<Tenant>("/api/tenants", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
      setShowCreate(false);
      setSlug("");
      setName("");
      setRootEmail("");
      setRootName("");
      setRootPassword("");
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const payload: {
      slug: string;
      name: string;
      root_user_email?: string;
      root_user_name?: string;
      root_user_password?: string;
    } = { slug, name };
    if (rootEmail) {
      payload.root_user_email = rootEmail;
      payload.root_user_name = rootName || undefined;
      payload.root_user_password = rootPassword || undefined;
    }
    createMutation.mutate(payload);
  }

  return (
    <section>
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            Tenant Provisioning
          </h1>
          <p className="text-sm text-slate-500">
            Create and manage customer/organization tenants (Super Admin)
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
            Provision New Customer
          </h2>

          <div className="mb-6">
            <h3 className="mb-3 text-sm font-medium text-slate-700">
              Organization Info
            </h3>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Tenant Slug
                </label>
                <input
                  type="text"
                  value={slug}
                  onChange={(e) =>
                    setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))
                  }
                  required
                  pattern="^[a-z0-9-]+$"
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                  placeholder="acme-corp"
                />
                <p className="mt-1 text-xs text-slate-400">
                  URL-friendly identifier (lowercase, hyphens only)
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Organization Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                  placeholder="ACME Corporation"
                />
              </div>
            </div>
          </div>

          <div className="mb-6 border-t border-slate-100 pt-4">
            <h3 className="mb-3 text-sm font-medium text-slate-700">
              Root Admin User (Primary Contact)
            </h3>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Admin Email
                </label>
                <input
                  type="email"
                  value={rootEmail}
                  onChange={(e) => setRootEmail(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                  placeholder="admin@acme-corp.com"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Admin Name
                </label>
                <input
                  type="text"
                  value={rootName}
                  onChange={(e) => setRootName(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                  placeholder="Jane Smith"
                />
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-slate-700">
                  Initial Password
                </label>
                <input
                  type="password"
                  value={rootPassword}
                  onChange={(e) => setRootPassword(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                  placeholder="Set initial password for the admin"
                />
              </div>
            </div>
            <p className="mt-2 text-xs text-slate-400">
              The root admin will be able to create additional users and manage
              roles within this tenant.
            </p>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={createMutation.isPending || !slug || !name}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
          >
            {createMutation.isPending
              ? "Provisioning..."
              : "Provision Tenant"}
          </button>
        </form>
      )}

      {tenantsQuery.isLoading && <p>Loading tenants...</p>}
      {tenantsQuery.error && (
        <p className="text-red-600">
          {(tenantsQuery.error as Error).message}
        </p>
      )}

      {tenantsQuery.data && tenantsQuery.data.length === 0 && !showCreate && (
        <div className="rounded-lg border-2 border-dashed border-slate-200 p-12 text-center">
          <p className="text-slate-500">No tenants provisioned yet.</p>
          <p className="mt-1 text-sm text-slate-400">
            Click &quot;New Tenant&quot; to provision a customer organization.
          </p>
        </div>
      )}

      {tenantsQuery.data && tenantsQuery.data.length > 0 && (
        <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Slug</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Created</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Login URL</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tenantsQuery.data.map((tenant) => (
                <tr key={tenant.id}>
                  <td className="px-4 py-3 text-sm text-slate-500">{tenant.id}</td>
                  <td className="px-4 py-3 text-sm font-mono text-slate-900">{tenant.slug}</td>
                  <td className="px-4 py-3 text-sm text-slate-700">{tenant.name}</td>
                  <td className="px-4 py-3">
                    {tenant.is_active ? (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">Active</span>
                    ) : (
                      <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">Inactive</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500">
                    {new Date(tenant.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <a
                      href={`/${tenant.slug}/login`}
                      className="text-brand underline hover:text-brand/80"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      /{tenant.slug}/login
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Tenant Admin: Own tenant management only ────────────────────────

function TenantAdminView() {
  const meta = getUserMeta();

  const myTenantQuery = useQuery<Tenant>({
    queryKey: ["my-tenant"],
    queryFn: () => apiClient.get<Tenant>("/api/tenants/me"),
  });

  return (
    <section>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">My Tenant</h1>
        <p className="text-sm text-slate-500">
          View and manage your organization settings
        </p>
      </header>

      {myTenantQuery.isLoading && <p>Loading tenant info...</p>}
      {myTenantQuery.error && (
        <p className="text-red-600">{(myTenantQuery.error as Error).message}</p>
      )}

      {myTenantQuery.data && (
        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-medium uppercase text-slate-400">Organization Name</p>
              <p className="text-sm text-slate-900">{myTenantQuery.data.name}</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase text-slate-400">Slug</p>
              <p className="text-sm font-mono text-slate-900">{myTenantQuery.data.slug}</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase text-slate-400">Status</p>
              {myTenantQuery.data.is_active ? (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">Active</span>
              ) : (
                <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">Inactive</span>
              )}
            </div>
            <div>
              <p className="text-xs font-medium uppercase text-slate-400">Created</p>
              <p className="text-sm text-slate-900">
                {new Date(myTenantQuery.data.created_at).toLocaleDateString()}
              </p>
            </div>
            <div className="col-span-2">
              <p className="text-xs font-medium uppercase text-slate-400">Login URL</p>
              <a
                href={`/${myTenantQuery.data.slug}/login`}
                className="text-sm text-brand underline hover:text-brand/80"
                target="_blank"
                rel="noopener noreferrer"
              >
                /{myTenantQuery.data.slug}/login
              </a>
            </div>
          </div>
          <div className="mt-4 border-t border-slate-100 pt-4">
            <p className="text-xs text-slate-400">
              To manage users within your tenant, go to Admin &gt; Users.
              Contact a super admin to provision new tenants.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
