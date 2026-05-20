"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

type TenantInfo = {
  id: number;
  slug: string;
  name: string;
};

type User = {
  id: number;
  tenant_id: number;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
};

const ROLES = ["viewer", "editor", "admin"];

export default function UsersPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("viewer");
  const [error, setError] = useState<string | null>(null);

  const tenantQuery = useQuery<TenantInfo>({
    queryKey: ["tenant-me"],
    queryFn: () => apiClient.get<TenantInfo>("/api/tenants/me"),
  });

  const tenantId = tenantQuery.data?.id;

  const usersQuery = useQuery<User[]>({
    queryKey: ["users", tenantId],
    queryFn: () => apiClient.get<User[]>(`/api/tenants/${tenantId}/users`),
    enabled: !!tenantId,
  });

  const createMutation = useMutation({
    mutationFn: (payload: {
      email: string;
      display_name: string;
      password: string;
      role: string;
    }) => apiClient.post<User>(`/api/tenants/${tenantId}/users`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users", tenantId] });
      setShowCreate(false);
      setEmail("");
      setDisplayName("");
      setPassword("");
      setRole("viewer");
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const updateRoleMutation = useMutation({
    mutationFn: ({ userId, newRole }: { userId: number; newRole: string }) =>
      apiClient.put<User>(`/api/tenants/${tenantId}/users/${userId}`, {
        role: newRole,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["users", tenantId] }),
  });

  const deactivateMutation = useMutation({
    mutationFn: (userId: number) =>
      apiClient.delete(`/api/tenants/${tenantId}/users/${userId}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["users", tenantId] }),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    createMutation.mutate({
      email,
      display_name: displayName,
      password,
      role,
    });
  }

  return (
    <section>
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            User Management
          </h1>
          {tenantQuery.data && (
            <p className="text-sm text-slate-500">
              Tenant: {tenantQuery.data.name} ({tenantQuery.data.slug})
            </p>
          )}
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90"
        >
          {showCreate ? "Cancel" : "Add User"}
        </button>
      </header>

      {showCreate && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
        >
          <h2 className="mb-4 text-lg font-medium text-slate-900">
            Create New User
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="user@example.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Display Name
              </label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="John Doe"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="Set initial password"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Role
              </label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r.charAt(0).toUpperCase() + r.slice(1)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="mt-4 rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
          >
            {createMutation.isPending ? "Creating..." : "Create User"}
          </button>
        </form>
      )}

      {usersQuery.isLoading && <p>Loading users...</p>}
      {usersQuery.error && (
        <p className="text-red-600">
          {(usersQuery.error as Error).message}
        </p>
      )}

      {usersQuery.data && (
        <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Email
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Role
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {usersQuery.data.map((user) => (
                <tr key={user.id}>
                  <td className="px-4 py-3 text-sm text-slate-900">
                    {user.email}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">
                    {user.display_name || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <select
                      value={user.role}
                      onChange={(e) =>
                        updateRoleMutation.mutate({
                          userId: user.id,
                          newRole: e.target.value,
                        })
                      }
                      className="rounded border border-slate-200 px-2 py-1 text-xs"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r.charAt(0).toUpperCase() + r.slice(1)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    {user.is_active ? (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
                        Active
                      </span>
                    ) : (
                      <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">
                        Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {user.is_active && (
                      <button
                        onClick={() => {
                          if (
                            confirm(
                              `Deactivate ${user.email}? They will no longer be able to log in.`
                            )
                          ) {
                            deactivateMutation.mutate(user.id);
                          }
                        }}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Deactivate
                      </button>
                    )}
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
