"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiClient } from "@/lib/api-client";
import type { Scope } from "@/types/scope";

export default function ScopesPage() {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Omit<Scope, "name" | "tenantId">>({
    sourceTable: "",
    sourceColumn: "",
    targetTable: "",
    targetColumn: "",
  });

  const list = useQuery<Scope[]>({
    queryKey: ["scopes"],
    queryFn: () => apiClient.get<Scope[]>("/api/scopes"),
  });

  const create = useMutation({
    mutationFn: () => apiClient.post<Scope>("/api/scopes", draft),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scopes"] }),
  });

  const remove = useMutation({
    mutationFn: ({ sourceTable, sourceColumn }: Scope) =>
      apiClient.delete(`/api/scopes/${sourceTable}/${sourceColumn}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scopes"] }),
  });

  return (
    <section>
      <h1 className="text-2xl font-semibold text-slate-900">Drill-down scopes</h1>
      <p className="mt-1 text-sm text-slate-600">
        Configure how columns drill into related tables.
      </p>

      <form
        className="mt-4 grid grid-cols-1 gap-3 rounded-md border border-slate-200 bg-white p-4 md:grid-cols-5"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        {(
          ["sourceTable", "sourceColumn", "targetTable", "targetColumn"] as const
        ).map((field) => (
          <input
            key={field}
            value={draft[field]}
            onChange={(e) =>
              setDraft((prev) => ({ ...prev, [field]: e.target.value }))
            }
            placeholder={field}
            className="rounded-md border border-slate-200 px-3 py-2 text-sm"
          />
        ))}
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg disabled:opacity-50"
        >
          {create.isPending ? "Adding…" : "Add scope"}
        </button>
      </form>

      {list.isLoading && <p className="mt-4">Loading…</p>}
      {list.error && (
        <p className="mt-4 text-sm text-red-600">
          {(list.error as Error).message}
        </p>
      )}

      {list.data && (
        <table className="mt-4 w-full overflow-hidden rounded-md border border-slate-200 bg-white text-sm">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="px-3 py-2 text-left">Source</th>
              <th className="px-3 py-2 text-left">→ Target</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((scope) => (
              <tr key={`${scope.sourceTable}.${scope.sourceColumn}`} className="border-t">
                <td className="px-3 py-2">
                  {scope.sourceTable}.{scope.sourceColumn}
                </td>
                <td className="px-3 py-2">
                  {scope.targetTable}.{scope.targetColumn}
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={() => remove.mutate(scope)}
                    className="rounded-md border border-slate-200 px-2 py-1 text-xs hover:bg-slate-50"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
