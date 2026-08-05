"use client";


import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createRepositoryConnection,
  deleteRepositoryConnection,
  getRepositoryProfile,
  listRepositoryConnections,
  listRepositoryItems,
  listRepositoryScans,
  listRepositoryConnectorTypes,
  startRepositoryScan,
  testExistingRepositoryConnection,
  testRepositoryConnectionConfig,
  updateRepositoryConnection,
  type RepositoryConnection,
  type RepositoryConnectionCreate,
  type RepositoryConnectionUpdate,
  type RepositoryItem,
  type RepositoryScan,
} from "@/lib/api/repository-connectors";import { classNames } from "./utils";



export function ConnectionDetail({ connection }: { connection: RepositoryConnection }) {
  const queryClient = useQueryClient();
  const [testResult, setTestResult] = useState<string | null>(null);

  const testMutation = useMutation({
    mutationFn: () => testExistingRepositoryConnection(connection.id),
    onSuccess: (result) => {
      const failed = result.checks.find((c) => c.status === "failed");
      setTestResult(
        failed?.message ?? (result.success ? "Connection test passed" : "Test failed"),
      );
    },
    onError: (err) => setTestResult(err instanceof Error ? err.message : "Test failed"),
  });

  const scanMutation = useMutation({
    mutationFn: () => startRepositoryScan(connection.id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["repository-scans", connection.id],
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteRepositoryConnection(connection.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repository-connections"] });
    },
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{connection.name}</h2>
          <p className="text-sm text-slate-500">{connection.connector_type}</p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand/90 disabled:opacity-50"
          >
            {scanMutation.isPending ? "Starting…" : "Scan now"}
          </button>
          <button
            type="button"
            onClick={() => testMutation.mutate()}
            disabled={testMutation.isPending}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {testMutation.isPending ? "Testing…" : "Test"}
          </button>
          <button
            type="button"
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
            className="rounded-md border border-red-200 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
          >
            Disable
          </button>
        </div>
      </div>

      {testResult && (
        <p
          className={classNames(
            "mb-4 rounded-md px-3 py-2 text-sm",
            testMutation.data?.success
              ? "bg-emerald-50 text-emerald-700"
              : "bg-red-50 text-red-700",
          )}
        >
          {testResult}
        </p>
      )}

      {scanMutation.isSuccess && scanMutation.data && (
        <p className="mb-4 rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-700">
          Scan {scanMutation.data.id} queued as job {scanMutation.data.job_id}.
        </p>
      )}

      <pre className="overflow-x-auto rounded-md bg-slate-50 p-3 text-xs text-slate-600">
        {JSON.stringify(connection.config, null, 2)}
      </pre>
    </div>
  );
}