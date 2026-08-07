"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteNetworkFileConnection,
  listNetworkFileConnections,
  type NetworkFileConnection,
} from "@/lib/api/network-file-connections";
import { NetworkConnectionForm } from "./network-connection-form";

function statusBadge(status: string | null) {
  if (status === "ok") {
    return <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">OK</span>;
  }
  if (status === "failed") {
    return <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">Failed</span>;
  }
  return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">—</span>;
}

export function NetworkConnectionsPanel({ onSaved }: { onSaved?: () => void } = {}) {
  const queryClient = useQueryClient();
  const [isCreating, setIsCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  const query = useQuery({
    queryKey: ["network-file-connections"],
    queryFn: listNetworkFileConnections,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteNetworkFileConnection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["network-file-connections"] });
      onSaved?.();
    },
  });

  const connections = query.data ?? [];
  const editing = connections.find((c) => c.id === editingId) ?? null;

  if (query.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (query.error) return <p className="text-sm text-red-600">{(query.error as Error).message}</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <p className="text-sm text-slate-500">
          Approved UNC/SMB locations that can be used in the Data Source Builder.
        </p>
        <button
          type="button"
          onClick={() => {
            setIsCreating(true);
            setEditingId(null);
          }}
          className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand/90"
        >
          Add network connection
        </button>
      </div>

      {(isCreating || editing) && (
        <NetworkConnectionForm
          connection={editing}
          onCancel={() => {
            setIsCreating(false);
            setEditingId(null);
          }}
          onDone={() => {
            setIsCreating(false);
            setEditingId(null);
            queryClient.invalidateQueries({ queryKey: ["network-file-connections"] });
            onSaved?.();
          }}
        />
      )}

      {connections.length === 0 && !isCreating && (
        <p className="text-sm text-slate-500">No network file connections configured yet.</p>
      )}

      {connections.length > 0 && (
        <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">UNC path</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">Enabled</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase text-slate-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {connections.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-sm font-medium text-slate-900">{c.name}</td>
                  <td className="px-4 py-3 text-sm font-mono text-slate-600">{c.label}</td>
                  <td className="px-4 py-3">{statusBadge(c.last_test_status)}</td>
                  <td className="px-4 py-3 text-sm text-slate-600">{c.enabled ? "Yes" : "No"}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(c.id);
                        setIsCreating(false);
                      }}
                      className="mr-2 text-sm font-medium text-brand hover:underline"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (confirm("Delete this network connection?")) {
                          deleteMutation.mutate(c.id);
                        }
                      }}
                      className="text-sm font-medium text-red-600 hover:underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
