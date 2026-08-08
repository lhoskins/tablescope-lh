"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  activateAnalyticalMethod,
  deactivateAnalyticalMethod,
  getAnalyticalMethod,
  getMethodCatalogOverview,
  listAnalyticalMethods,
  type MethodListParams,
  type MethodSummary,
} from "@/lib/api/analytical-methods";

const PAGE_SIZE = 25;

const STATUS_STYLES: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-700",
  approved: "bg-sky-50 text-sky-700",
  ready_for_review: "bg-amber-50 text-amber-700",
  draft: "bg-slate-100 text-slate-600",
  validation_failed: "bg-red-50 text-red-700",
  retired: "bg-slate-100 text-slate-400",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function TierBadge({ tier }: { tier: number }) {
  return (
    <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
      Tier {tier}
    </span>
  );
}

function EngineBadge({ engine }: { engine: string | null }) {
  const normalized = (engine || "python").toLowerCase();
  const cls =
    normalized === "r"
      ? "bg-indigo-50 text-indigo-700"
      : "bg-emerald-50 text-emerald-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {normalized === "r" ? "R" : "Python"}
    </span>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-2xl font-semibold text-slate-900">{value}</div>
      <div className="mt-0.5 text-xs uppercase tracking-wide text-slate-500">
        {label}
      </div>
    </div>
  );
}

function ActivationToggle({ method, onSuccess }: { method: MethodSummary; onSuccess?: () => void }) {
  const queryClient = useQueryClient();
  const activate = useMutation({
    mutationFn: () => activateAnalyticalMethod(method.method_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analytical-methods"] });
      queryClient.invalidateQueries({ queryKey: ["analytical-method", method.method_id] });
      onSuccess?.();
    },
  });
  const deactivate = useMutation({
    mutationFn: () => deactivateAnalyticalMethod(method.method_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analytical-methods"] });
      queryClient.invalidateQueries({ queryKey: ["analytical-method", method.method_id] });
      onSuccess?.();
    },
  });

  const busy = activate.isPending || deactivate.isPending;
  if (!method.implementation_available) {
    return (
      <span
        className="cursor-help text-xs text-slate-400"
        title="No Python or R implementation for this method"
      >
        No impl
      </span>
    );
  }
  if (method.is_executable) {
    return (
      <button
        type="button"
        disabled={busy}
        onClick={(e) => {
          e.stopPropagation();
          deactivate.mutate();
        }}
        className="rounded-md border border-line-tertiary px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
      >
        {busy ? "…" : "Deactivate"}
      </button>
    );
  }
  return (
    <button
      type="button"
      disabled={busy}
      onClick={(e) => {
        e.stopPropagation();
        activate.mutate();
      }}
      className="rounded-md bg-brand-600 px-2 py-1 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
    >
      {busy ? "…" : "Activate"}
    </button>
  );
}

export default function AnalyticalMethodsPage() {
  const [tier, setTier] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [category, setCategory] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  const overviewQuery = useQuery({
    queryKey: ["method-catalog-overview"],
    queryFn: getMethodCatalogOverview,
  });

  const params: MethodListParams = {
    tier: tier ? Number(tier) : undefined,
    status: status || undefined,
    category: category || undefined,
    q: search.trim() || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };

  const methodsQuery = useQuery({
    queryKey: ["analytical-methods", params],
    queryFn: () => listAnalyticalMethods(params),
  });

  const overview = overviewQuery.data;
  const categories = overview ? Object.keys(overview.by_category) : [];
  const statuses = overview ? Object.keys(overview.by_status) : [];
  const total = methodsQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function resetPage<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(0);
    };
  }

  return (
    <section>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">
          Analytical Methods
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          The governed Tablescope Analytical Reference Method catalog. Methods
          flow through draft → approved → active; only active, executable methods
          run at query time.
          {overview?.version && (
            <>
              {" "}
              Catalog <span className="font-medium">{overview.name}</span> v
              {overview.version.version} ({overview.version.status}).
            </>
          )}
        </p>
      </header>

      {overviewQuery.isLoading && <p className="text-sm text-slate-500">Loading catalog…</p>}
      {overviewQuery.error && (
        <p className="text-sm text-red-600">
          {(overviewQuery.error as Error).message}
        </p>
      )}

      {overview && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Total methods" value={overview.methods_total} />
          <StatCard label="Executable (live)" value={overview.executable_total} />
          {Object.entries(overview.by_tier)
            .sort()
            .slice(0, 2)
            .map(([k, v]) => (
              <StatCard key={k} label={k.replace("_", " ")} value={v} />
            ))}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-xs text-slate-500">
          Search
          <input
            type="text"
            value={search}
            onChange={(e) => resetPage(setSearch)(e.target.value)}
            placeholder="Name or id…"
            className="mt-1 w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </label>
        <label className="flex flex-col text-xs text-slate-500">
          Tier
          <select
            value={tier}
            onChange={(e) => resetPage(setTier)(e.target.value)}
            className="mt-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">All</option>
            <option value="1">Tier 1</option>
            <option value="2">Tier 2</option>
            <option value="3">Tier 3</option>
            <option value="4">Tier 4</option>
          </select>
        </label>
        <label className="flex flex-col text-xs text-slate-500">
          Status
          <select
            value={status}
            onChange={(e) => resetPage(setStatus)(e.target.value)}
            className="mt-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">All</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs text-slate-500">
          Category
          <select
            value={category}
            onChange={(e) => resetPage(setCategory)(e.target.value)}
            className="mt-1 max-w-[200px] rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">All</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>

      {methodsQuery.isLoading && <p className="text-sm text-slate-500">Loading methods…</p>}
      {methodsQuery.data && methodsQuery.data.methods.length === 0 && (
        <p className="text-sm text-slate-500">No methods match these filters.</p>
      )}

      {methodsQuery.data && methodsQuery.data.methods.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
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
                  Tier
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Engine
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Activation
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {methodsQuery.data.methods.map((m: MethodSummary) => (
                <tr
                  key={m.id}
                  onClick={() => setSelected(m.method_id)}
                  className="cursor-pointer hover:bg-slate-50"
                >
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-slate-900">
                      {m.display_name}
                    </div>
                    <div className="text-xs text-slate-400">{m.method_id}</div>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">
                    {m.category || "—"}
                    {m.subcategory ? (
                      <span className="text-slate-400"> / {m.subcategory}</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    <TierBadge tier={m.tier} />
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={m.status} />
                  </td>
                  <td className="px-4 py-3">
                    <EngineBadge engine={m.execution_engine} />
                  </td>
                  <td className="px-4 py-3">
                    <ActivationToggle method={m} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
          <span>
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {selected && (
        <MethodDetailDrawer methodId={selected} onClose={() => setSelected(null)} />
      )}
    </section>
  );
}

function MethodDetailDrawer({
  methodId,
  onClose,
}: {
  methodId: string;
  onClose: () => void;
}) {
  const detailQuery = useQuery({
    queryKey: ["analytical-method", methodId],
    queryFn: () => getAnalyticalMethod(methodId),
  });
  const d = detailQuery.data;

  return (
    <div
      className="fixed inset-0 z-30 flex justify-end bg-black/30"
      onClick={onClose}
    >
      <div
        className="h-full w-full max-w-lg overflow-y-auto bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {d?.display_name ?? methodId}
            </h2>
            <div className="text-xs text-slate-400">{methodId}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-slate-400 hover:bg-slate-100"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {detailQuery.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
        {detailQuery.error && (
          <p className="text-sm text-red-600">
            {(detailQuery.error as Error).message}
          </p>
        )}

        {d && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <TierBadge tier={d.tier} />
              <StatusBadge status={d.status} />
              <EngineBadge engine={d.execution_engine} />
              {d.is_executable && (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                  Executable
                </span>
              )}
              {d && <ActivationToggle method={d} onSuccess={() => detailQuery.refetch()} />}
            </div>

            {d.category && (
              <div className="text-slate-500">
                {d.category}
                {d.subcategory ? ` / ${d.subcategory}` : ""}
              </div>
            )}

            {d.summary && <p className="text-slate-700">{d.summary}</p>}

            {d.applicability_condition && (
              <div>
                <div className="mb-1 text-xs font-medium uppercase text-slate-400">
                  Applicability
                </div>
                <p className="text-slate-700">{d.applicability_condition}</p>
              </div>
            )}

            {d.supported_intents.length > 0 && (
              <div>
                <div className="mb-1 text-xs font-medium uppercase text-slate-400">
                  Supported intents
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {d.supported_intents.map((i) => (
                    <span
                      key={i}
                      className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
                    >
                      {i}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {d.executor_key && (
              <div>
                <div className="mb-1 text-xs font-medium uppercase text-slate-400">
                  Executor
                </div>
                <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">
                  {d.executor_key}
                </code>
              </div>
            )}

            {Object.keys(d.method_card ?? {}).length > 0 && (
              <div>
                <div className="mb-1 text-xs font-medium uppercase text-slate-400">
                  Method card
                </div>
                <pre className="overflow-x-auto rounded-md bg-slate-50 p-3 text-xs text-slate-600">
                  {JSON.stringify(d.method_card, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
