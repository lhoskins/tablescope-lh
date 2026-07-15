"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getAIPolicy,
  getMethodCatalog,
  updateMethodPolicy,
  bulkUpdatePolicy,
  listGovernanceAudit,
  type MethodCatalogItem,
  type MethodPolicy,
  type AuditEvent,
} from "@/lib/api/ai-governance";

const PAGE_SIZE = 25;
const AUDIT_PAGE_SIZE = 20;

function RiskBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    low: "bg-emerald-50 text-emerald-700",
    medium: "bg-amber-50 text-amber-700",
    high: "bg-rose-50 text-rose-700",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[level] ?? "bg-slate-100 text-slate-600"}`}
    >
      {level}
    </span>
  );
}

function DecisionBadge({ decision }: { decision: string | null }) {
  if (!decision) return <span className="text-slate-400">—</span>;
  const styles: Record<string, string> = {
    allowed: "bg-emerald-50 text-emerald-700",
    fallback: "bg-sky-50 text-sky-700",
    blocked: "bg-rose-50 text-rose-700",
    changed: "bg-amber-50 text-amber-700",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[decision] ?? "bg-slate-100 text-slate-600"}`}
    >
      {decision}
    </span>
  );
}

export default function AIGovernancePage() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState("");
  const [filterRisk, setFilterRisk] = useState("");
  const [auditPage, setAuditPage] = useState(0);
  const [auditFilters, setAuditFilters] = useState({
    event_type: "",
    method_key: "",
    decision: "",
  });

  const policyQuery = useQuery({
    queryKey: ["ai-governance-policy"],
    queryFn: getAIPolicy,
  });

  const catalogQuery = useQuery({
    queryKey: ["ai-governance-catalog"],
    queryFn: getMethodCatalog,
  });

  const auditQuery = useQuery({
    queryKey: ["ai-governance-audit", auditFilters, auditPage],
    queryFn: () =>
      listGovernanceAudit({
        event_type: auditFilters.event_type || undefined,
        method_key: auditFilters.method_key || undefined,
        decision: auditFilters.decision || undefined,
        limit: AUDIT_PAGE_SIZE,
        offset: auditPage * AUDIT_PAGE_SIZE,
      }),
  });

  const policy = policyQuery.data;
  const catalog = useMemo(
    () => catalogQuery.data?.methods ?? [],
    [catalogQuery.data],
  );

  const methodEntries = useMemo(() => {
    const policies = policy?.methods ?? {};
    const list: Array<{ key: string; policy: MethodPolicy; catalog?: MethodCatalogItem }> = [];
    for (const key of Object.keys(policies).sort()) {
      list.push({
        key,
        policy: policies[key],
        catalog: catalog.find((m) => m.key === key),
      });
    }
    return list;
  }, [policy, catalog]);

  const filteredMethods = useMemo(() => {
    return methodEntries.filter((m) => {
      if (filterCategory && m.catalog?.category !== filterCategory) return false;
      if (filterRisk && m.policy.riskLevel !== filterRisk) return false;
      return true;
    });
  }, [methodEntries, filterCategory, filterRisk]);

  const categories = useMemo(
    () => Array.from(new Set(catalog.map((m) => m.category))).sort(),
    [catalog],
  );
  const riskLevels = useMemo(
    () => Array.from(new Set(methodEntries.map((m) => m.policy.riskLevel))).sort(),
    [methodEntries],
  );

  const updateMutation = useMutation({
    mutationFn: async ({
      key,
      enabled,
      reason,
    }: {
      key: string;
      enabled: boolean;
      reason?: string;
    }) => {
      const current = policy?.version ?? 0;
      return updateMethodPolicy(key, {
        enabled,
        reason,
        expected_version: current,
      });
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["ai-governance-policy"], data);
      setSuccess("Policy updated.");
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message);
      setSuccess(null);
      policyQuery.refetch();
    },
  });

  const stats = useMemo(() => {
    const enabled = methodEntries.filter((m) => m.policy.enabled).length;
    const disabled = methodEntries.length - enabled;
    const highRisk = methodEntries.filter((m) => m.policy.riskLevel === "high" && m.policy.enabled).length;
    const experimental = methodEntries.filter((m) => m.policy.experimental && m.policy.enabled).length;
    return { total: methodEntries.length, enabled, disabled, highRisk, experimental };
  }, [methodEntries]);

  function handleToggle(key: string, enabled: boolean) {
    updateMutation.mutate({ key, enabled, reason: undefined });
  }

  function handleReason(key: string, reason: string) {
    updateMutation.mutate({ key, enabled: false, reason });
  }

  return (
    <section className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900">AI Governance</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Control which analytical methods the AI is allowed to use for your
          organization. Disabled methods are blocked before execution; fallback
          methods are used when a safe alternative is available.
        </p>
      </header>

      {policyQuery.isLoading && <p className="text-sm text-slate-500">Loading policy…</p>}
      {policyQuery.error && (
        <p className="text-sm text-red-600">{(policyQuery.error as Error).message}</p>
      )}

      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-700">
          {success}
        </div>
      )}

      {policy && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="text-2xl font-semibold text-slate-900">{stats.total}</div>
              <div className="mt-0.5 text-xs uppercase tracking-wide text-slate-500">
                Total methods
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="text-2xl font-semibold text-emerald-700">{stats.enabled}</div>
              <div className="mt-0.5 text-xs uppercase tracking-wide text-slate-500">
                Enabled
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="text-2xl font-semibold text-rose-700">{stats.disabled}</div>
              <div className="mt-0.5 text-xs uppercase tracking-wide text-slate-500">
                Disabled
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="text-2xl font-semibold text-slate-900">{policy.version}</div>
              <div className="mt-0.5 text-xs uppercase tracking-wide text-slate-500">
                Policy version
              </div>
            </div>
          </div>

          <div>
            <div className="mb-4 flex flex-wrap items-end gap-3">
              <h2 className="mr-auto text-lg font-medium text-slate-900">
                Method Policies
              </h2>
              <label className="flex flex-col text-xs text-slate-500">
                Category
                <select
                  value={filterCategory}
                  onChange={(e) => setFilterCategory(e.target.value)}
                  className="mt-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                >
                  <option value="">All</option>
                  {categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col text-xs text-slate-500">
                Risk
                <select
                  value={filterRisk}
                  onChange={(e) => setFilterRisk(e.target.value)}
                  className="mt-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                >
                  <option value="">All</option>
                  {riskLevels.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                      Method
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                      Category
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                      Risk
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                      Source
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                      Enabled
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                      Reason
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filteredMethods.map((m) => (
                    <tr key={m.key} className="hover:bg-slate-50">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="text-sm font-medium text-slate-900">
                            {m.policy.displayName}
                          </div>
                          {m.policy.experimental && (
                            <span className="rounded-full bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-700">
                              experimental
                            </span>
                          )}
                        </div>
                        <div className="max-w-md text-xs text-slate-500">
                          {m.policy.description}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600">
                        {m.policy.category}
                      </td>
                      <td className="px-4 py-3">
                        <RiskBadge level={m.policy.riskLevel} />
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600">
                        {m.policy.source.replace("_", " ")}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          role="switch"
                          aria-checked={m.policy.enabled}
                          onClick={() => handleToggle(m.key, !m.policy.enabled)}
                          disabled={updateMutation.isPending}
                          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${m.policy.enabled ? "bg-brand-600" : "bg-slate-300"} disabled:opacity-50`}
                        >
                          <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${m.policy.enabled ? "translate-x-6" : "translate-x-1"}`}
                          />
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <input
                          type="text"
                          defaultValue={m.policy.reason ?? ""}
                          onBlur={(e) => {
                            if (e.target.value !== (m.policy.reason ?? "")) {
                              handleReason(m.key, e.target.value);
                            }
                          }}
                          placeholder="Reason for override…"
                          className="w-48 rounded-md border border-slate-300 px-2 py-1 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                        />
                      </td>
                    </tr>
                  ))}
                  {filteredMethods.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-6 text-center text-sm text-slate-500">
                        No methods match the selected filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <h2 className="mb-4 text-lg font-medium text-slate-900">Audit History</h2>
            <div className="mb-4 flex flex-wrap items-end gap-3">
              <label className="flex flex-col text-xs text-slate-500">
                Event type
                <input
                  type="text"
                  value={auditFilters.event_type}
                  onChange={(e) =>
                    setAuditFilters((f) => ({ ...f, event_type: e.target.value }))
                  }
                  placeholder="ai_governance.method_blocked"
                  className="mt-1 w-56 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                />
              </label>
              <label className="flex flex-col text-xs text-slate-500">
                Method
                <input
                  type="text"
                  value={auditFilters.method_key}
                  onChange={(e) =>
                    setAuditFilters((f) => ({ ...f, method_key: e.target.value }))
                  }
                  placeholder="forecast"
                  className="mt-1 w-40 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                />
              </label>
              <label className="flex flex-col text-xs text-slate-500">
                Decision
                <select
                  value={auditFilters.decision}
                  onChange={(e) =>
                    setAuditFilters((f) => ({ ...f, decision: e.target.value }))
                  }
                  className="mt-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                >
                  <option value="">All</option>
                  <option value="allowed">allowed</option>
                  <option value="fallback">fallback</option>
                  <option value="blocked">blocked</option>
                  <option value="changed">changed</option>
                </select>
              </label>
            </div>

            {auditQuery.isLoading && <p className="text-sm text-slate-500">Loading audit…</p>}
            {auditQuery.error && (
              <p className="text-sm text-red-600">{(auditQuery.error as Error).message}</p>
            )}

            {auditQuery.data && (
              <>
                <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
                  <table className="min-w-full divide-y divide-slate-200">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                          Time
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                          Event
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                          Method
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                          Decision
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                          Actor
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {auditQuery.data.events.map((event: AuditEvent) => (
                        <tr key={event.id} className="hover:bg-slate-50">
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-slate-600">
                            {new Date(event.created_at).toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-sm text-slate-900">
                            {event.event_type}
                          </td>
                          <td className="px-4 py-3 text-sm text-slate-600">
                            {event.method_key ?? "—"}
                          </td>
                          <td className="px-4 py-3">
                            <DecisionBadge decision={event.decision} />
                          </td>
                          <td className="px-4 py-3 text-sm text-slate-600">
                            {event.actor_type}
                            {event.actor_user_id ? ` #${event.actor_user_id}` : ""}
                          </td>
                        </tr>
                      ))}
                      {auditQuery.data.events.length === 0 && (
                        <tr>
                          <td colSpan={5} className="px-4 py-6 text-center text-sm text-slate-500">
                            No audit events match these filters.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                {auditQuery.data.total > AUDIT_PAGE_SIZE && (
                  <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
                    <span>
                      {auditPage * AUDIT_PAGE_SIZE + 1}–
                      {Math.min((auditPage + 1) * AUDIT_PAGE_SIZE, auditQuery.data.total)} of{" "}
                      {auditQuery.data.total}
                    </span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setAuditPage((p) => Math.max(0, p - 1))}
                        disabled={auditPage === 0}
                        className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
                      >
                        Previous
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setAuditPage((p) =>
                            p + 1 < Math.ceil(auditQuery.data.total / AUDIT_PAGE_SIZE)
                              ? p + 1
                              : p,
                          )
                        }
                        disabled={
                          (auditPage + 1) * AUDIT_PAGE_SIZE >= auditQuery.data.total
                        }
                        className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}
    </section>
  );
}
