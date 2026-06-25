"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

type AllowedDomain = {
  id: number;
  domain: string;
  is_active: boolean;
};

type AllowedDomainsResponse = {
  enabled: boolean;
  domains: AllowedDomain[];
};

const QUERY_KEY = ["allowed-domains"] as const;
const DOMAIN_RE = /^(?!-)[a-z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-z0-9-]{1,63}(?<!-))*\.[a-z]{2,}$/;

export default function AllowedDomainsPage() {
  const queryClient = useQueryClient();
  const [newDomain, setNewDomain] = useState("");
  const [error, setError] = useState<string | null>(null);

  const domainsQuery = useQuery<AllowedDomainsResponse>({
    queryKey: QUERY_KEY,
    queryFn: () =>
      apiClient.get<AllowedDomainsResponse>(
        "/api/tenants/current/allowed-domains",
      ),
  });

  const enabled = domainsQuery.data?.enabled ?? false;
  const domains = domainsQuery.data?.domains ?? [];

  const toggleMutation = useMutation({
    mutationFn: (next: boolean) =>
      apiClient.put<AllowedDomainsResponse>(
        "/api/tenants/current/allowed-domains/settings",
        { enabled: next },
      ),
    onSuccess: (data) => queryClient.setQueryData(QUERY_KEY, data),
    onError: (err: Error) => setError(err.message),
  });

  const addMutation = useMutation({
    mutationFn: (domain: string) =>
      apiClient.post<AllowedDomain>("/api/tenants/current/allowed-domains", {
        domain,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setNewDomain("");
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete(`/api/tenants/current/allowed-domains/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
    onError: (err: Error) => setError(err.message),
  });

  function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const normalized = newDomain.trim().toLowerCase().replace(/^@/, "");
    if (!normalized) return;
    if (normalized.includes("*") || !DOMAIN_RE.test(normalized)) {
      setError(
        "Enter a valid bare domain like boeing.com (no wildcards or @).",
      );
      return;
    }
    if (domains.some((d) => d.domain === normalized)) {
      setError("That domain is already on the list.");
      return;
    }
    addMutation.mutate(normalized);
  }

  return (
    <section className="max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Allowed Domains</h1>
        <p className="mt-1 text-sm text-slate-500">
          When enabled, only users with approved email domains can be invited,
          create accounts, receive tenant transaction emails, and access this
          tenant. The original tenant owner remains exempt so they cannot be
          locked out.
        </p>
      </header>

      {domainsQuery.isLoading && <p>Loading…</p>}
      {domainsQuery.error && (
        <p className="text-red-600">{(domainsQuery.error as Error).message}</p>
      )}

      {domainsQuery.data && (
        <div className="space-y-6">
          <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div>
              <div className="text-sm font-medium text-slate-900">
                Enable allowed domains
              </div>
              <div className="text-xs text-slate-500">
                {enabled
                  ? "Access is restricted to the domains below."
                  : "No domain restriction (anyone invited may join)."}
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label="Enable allowed domains"
              onClick={() => toggleMutation.mutate(!enabled)}
              disabled={toggleMutation.isPending}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                enabled ? "bg-brand" : "bg-slate-300"
              } disabled:opacity-50`}
            >
              <span
                className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${
                  enabled ? "translate-x-5" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-sm font-medium text-slate-900">
              Approved domains
            </h2>
            <form onSubmit={handleAdd} className="mb-4 flex gap-2">
              <input
                type="text"
                value={newDomain}
                onChange={(e) => setNewDomain(e.target.value)}
                placeholder="boeing.com"
                className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
              />
              <button
                type="submit"
                disabled={addMutation.isPending}
                className="shrink-0 rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
              >
                Add
              </button>
            </form>
            {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

            {domains.length === 0 ? (
              <p className="text-sm text-slate-500">
                No domains added yet. Add at least one before enabling the
                restriction.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {domains.map((d) => (
                  <li
                    key={d.id}
                    className="flex items-center justify-between py-2"
                  >
                    <span className="text-sm text-slate-800">{d.domain}</span>
                    <button
                      type="button"
                      onClick={() => removeMutation.mutate(d.id)}
                      disabled={removeMutation.isPending}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
