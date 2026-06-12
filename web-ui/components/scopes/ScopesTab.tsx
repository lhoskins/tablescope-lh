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

  // Manual creation state
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newSourceQuery, setNewSourceQuery] = useState<number | "">("");
  const [newSourceField, setNewSourceField] = useState("");
  const [newTargetQuery, setNewTargetQuery] = useState<number | "">("");
  const [newTargetField, setNewTargetField] = useState("");
  const [sourceFields, setSourceFields] = useState<string[]>([]);
  const [targetFields, setTargetFields] = useState<string[]>([]);
  const [loadingFields, setLoadingFields] = useState(false);

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

  // Load columns when source/target query changes
  const loadColumns = useCallback(async (queryId: number, target: "source" | "target") => {
    setLoadingFields(true);
    try {
      const q = queries.find((qq) => qq.id === queryId);
      if (!q) return;
      const result = await apiClient.get<{ columns: string[] }>(`/api/projects/${projectId}/queries/${queryId}/columns`);
      if (target === "source") setSourceFields(result.columns || []);
      else setTargetFields(result.columns || []);
    } catch {
      // If columns endpoint doesn't exist, try running the query to get columns
      try {
        const queryData = await apiClient.get<{ sql_text: string }>(`/api/projects/${projectId}/queries/${queryId}`);
        if (queryData.sql_text) {
          const result = await apiClient.post<{ columns: string[]; rows: Record<string, unknown>[] }>(`/api/query/execute`, {
            project_id: projectId,
            sql_text: queryData.sql_text,
            limit: 1,
          });
          const cols = result.columns || (result.rows?.[0] ? Object.keys(result.rows[0]) : []);
          if (target === "source") setSourceFields(cols);
          else setTargetFields(cols);
        }
      } catch {
        // Silently fail — user can type manually
      }
    } finally {
      setLoadingFields(false);
    }
  }, [projectId, queries]);

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

  const handleCreate = async () => {
    if (!newSourceQuery || !newSourceField.trim() || !newTargetQuery || !newTargetField.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await apiClient.post("/api/query-scopes", {
        query_id: newSourceQuery,
        source_field: newSourceField.trim(),
        target_query_id: newTargetQuery,
        target_field: newTargetField.trim(),
      });
      setShowCreate(false);
      setNewSourceQuery("");
      setNewSourceField("");
      setNewTargetQuery("");
      setNewTargetField("");
      setSourceFields([]);
      setTargetFields([]);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create scope");
    } finally {
      setCreating(false);
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
        <div className="flex gap-2">
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            {showCreate ? "Cancel" : "Create Scope"}
          </button>
          <button
            onClick={loadData}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Create Scope Form */}
      {showCreate && (
        <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-900">Create New Scope</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">Source Query</label>
              <select
                value={newSourceQuery}
                onChange={(e) => {
                  const val = Number(e.target.value) || "";
                  setNewSourceQuery(val);
                  setNewSourceField("");
                  setSourceFields([]);
                  if (val) loadColumns(val as number, "source");
                }}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">Select query...</option>
                {queries.map((q) => (
                  <option key={q.id} value={q.id}>{q.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">Source Field</label>
              {sourceFields.length > 0 ? (
                <select
                  value={newSourceField}
                  onChange={(e) => setNewSourceField(e.target.value)}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">Select field...</option>
                  {sourceFields.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={newSourceField}
                  onChange={(e) => setNewSourceField(e.target.value)}
                  placeholder="Field name..."
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
              )}
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">Target Query</label>
              <select
                value={newTargetQuery}
                onChange={(e) => {
                  const val = Number(e.target.value) || "";
                  setNewTargetQuery(val);
                  setNewTargetField("");
                  setTargetFields([]);
                  if (val) loadColumns(val as number, "target");
                }}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">Select query...</option>
                {queries.map((q) => (
                  <option key={q.id} value={q.id}>{q.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">Target Field</label>
              {targetFields.length > 0 ? (
                <select
                  value={newTargetField}
                  onChange={(e) => setNewTargetField(e.target.value)}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">Select field...</option>
                  {targetFields.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={newTargetField}
                  onChange={(e) => setNewTargetField(e.target.value)}
                  placeholder="Field name..."
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
              )}
            </div>
          </div>
          {loadingFields && (
            <p className="mt-2 text-xs text-slate-500">Loading fields...</p>
          )}
          <div className="mt-3 flex gap-2">
            <button
              onClick={handleCreate}
              disabled={creating || !newSourceQuery || !newSourceField.trim() || !newTargetQuery || !newTargetField.trim()}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {creating ? "Creating..." : "Create Scope"}
            </button>
            <button
              onClick={() => { setShowCreate(false); setSourceFields([]); setTargetFields([]); }}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {scopes.length === 0 && !showCreate ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
          <p className="text-sm text-slate-500">No scopes configured for this project.</p>
          <p className="mt-1 text-xs text-slate-400">
            Click &quot;Create Scope&quot; above to add one manually, or use the AI tab to generate suggestions.
          </p>
        </div>
      ) : scopes.length > 0 ? (
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
      ) : null}
    </div>
  );
}
