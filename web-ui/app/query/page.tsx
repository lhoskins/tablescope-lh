"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { DataGrid } from "@/components/data-grid/DataGrid";
import { apiClient } from "@/lib/api-client";

type QueryResponse = {
  columns: string[];
  rows: Record<string, unknown>[];
  total?: number;
  drilldownUsed: boolean;
  targetTable: string | null;
  targetColumn: string | null;
};

export default function QueryPage() {
  const [projectId, setProjectId] = useState("1");
  const [tableName, setTableName] = useState("");
  const [columnName, setColumnName] = useState("");
  const [filterValue, setFilterValue] = useState("");
  const [limit, setLimit] = useState("1000");

  const mutation = useMutation({
    mutationFn: () =>
      apiClient.post<QueryResponse>("/api/query/fetch", {
        projectId: Number(projectId),
        tableName,
        columnName: columnName || null,
        value: filterValue || null,
        limit: Number(limit),
      }),
  });

  return (
    <section>
      <h1 className="text-2xl font-semibold text-slate-900">Query</h1>
      <form
        className="mt-4 grid grid-cols-1 gap-3 rounded-md border border-slate-200 bg-white p-4 md:grid-cols-5"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <input
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          placeholder="Project ID"
          className="rounded-md border border-slate-200 px-3 py-2 text-sm"
        />
        <input
          value={tableName}
          onChange={(e) => setTableName(e.target.value)}
          placeholder="Table"
          className="rounded-md border border-slate-200 px-3 py-2 text-sm"
        />
        <input
          value={columnName}
          onChange={(e) => setColumnName(e.target.value)}
          placeholder="Column (optional)"
          className="rounded-md border border-slate-200 px-3 py-2 text-sm"
        />
        <input
          value={filterValue}
          onChange={(e) => setFilterValue(e.target.value)}
          placeholder="Value (drill-down)"
          className="rounded-md border border-slate-200 px-3 py-2 text-sm"
        />
        <input
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
          placeholder="Limit"
          className="rounded-md border border-slate-200 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={mutation.isPending || !tableName}
          className="col-span-full rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg disabled:opacity-50"
        >
          {mutation.isPending ? "Running…" : "Run query"}
        </button>
      </form>

      {mutation.error && (
        <p className="mt-4 text-sm text-red-600">
          {(mutation.error as Error).message}
        </p>
      )}

      {mutation.data && (
        <div className="mt-4 space-y-2">
          {mutation.data.drilldownUsed && (
            <p className="text-sm text-emerald-700">
              Drill-down applied → {mutation.data.targetTable}.{mutation.data.targetColumn}
            </p>
          )}
          <DataGrid columns={mutation.data.columns} rows={mutation.data.rows} total={mutation.data.total} />
        </div>
      )}
    </section>
  );
}
