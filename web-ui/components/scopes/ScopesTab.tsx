"use client";

import { useState, useEffect, useCallback } from "react";
import { apiClient } from "@/lib/api-client";

type QueryScopeRow = {
  id: number;
  tenant_id: number;
  project_id: number;
  query_id: number;
  source_field: string;
  target_query_id: number;
  target_field: string;
};

type SavedQueryRef = {
  id: number;
  name: string;
};

type Props = {
  projectId: number;
};

export function ScopesTab({ projectId }: Props) {
  const [scopes, setScopes] = useState<QueryScopeRow[]>([]);
  const [queries, setQueries] = useState<SavedQueryRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  const queryName = useCallback(
    (qid: number) => queries.find((q) => q.id === qid)?.name ?? `Query #${qid}`,
    [queries],
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [scopeData, queryData] = await Promise.all([
        apiClient.get<QueryScopeRow[]>(`/api/query-scopes?project_id=${projectId}`),
        apiClient.get<SavedQueryRef[]>(`/api/projects/${projectId}/queries`),
      ]);
      setScopes(scopeData);
      setQueries(queryData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load scopes");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleDelete = async (scopeId: number) => {
    setDeleting(scopeId);
    try {
      await apiClient.delete(`/api/query-scopes/${scopeId}`);
      setScopes((prev) => prev.filter((s) => s.id !== scopeId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete scope");
    } finally {
      setDeleting(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-slate-500">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        Loading scopes...
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Query Scopes</h2>
          <p className="text-sm text-slate-500">
            Drill-down relationships between saved queries. Click a scoped cell in a query result to drill into the target query filtered by that value.
          </p>
        </div>
        <button
          onClick={loadData}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {scopes.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
          <p className="text-sm text-slate-500">No scopes configured for this project.</p>
          <p className="mt-1 text-xs text-slate-400">
            Use the AI tab → Scope Map to generate scope suggestions, or create them manually.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
                  ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
                  Source Query
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
                  Source Field
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
                  →
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
                  Target Query
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-slate-500">
                  Target Field
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-slate-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {scopes.map((scope) => (
                <tr key={scope.id} className="hover:bg-slate-50">
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-slate-500">
                    {scope.id}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <span className="rounded bg-blue-100 px-2 py-0.5 font-medium text-blue-800">
                      {queryName(scope.query_id)}
                    </span>
                    <span className="ml-1 text-xs text-slate-400">#{scope.query_id}</span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-sm text-slate-700">
                    {scope.source_field}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-slate-400">→</td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <span className="rounded bg-indigo-100 px-2 py-0.5 font-medium text-indigo-800">
                      {queryName(scope.target_query_id)}
                    </span>
                    <span className="ml-1 text-xs text-slate-400">#{scope.target_query_id}</span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-sm text-slate-700">
                    {scope.target_field}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    <button
                      onClick={() => handleDelete(scope.id)}
                      disabled={deleting === scope.id}
                      className="rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                    >
                      {deleting === scope.id ? "Deleting..." : "Delete"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500">
            {scopes.length} scope{scopes.length !== 1 ? "s" : ""} total
          </div>
        </div>
      )}
    </div>
  );
}
