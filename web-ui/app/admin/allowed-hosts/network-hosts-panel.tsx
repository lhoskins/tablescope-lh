"use client";

import { useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import {
  createNetworkHost,
  deleteNetworkHost,
  listNetworkHosts,
  updateNetworkHost,
  type NetworkHost,
} from "@/lib/api/network-file-connections";

export function NetworkHostsPanel() {
  const queryClient = useQueryClient();
  const { data: hosts = [], isLoading } = useQuery({
    queryKey: ["network-hosts"],
    queryFn: listNetworkHosts,
  });

  const [editing, setEditing] = useState<NetworkHost | null>(null);
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: deleteNetworkHost,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["network-hosts"] });
    },
  });

  const resetForm = () => {
    setEditing(null);
    setName("");
    setHost("");
    setEnabled(true);
    setError(null);
  };

  const startEdit = (h: NetworkHost) => {
    setEditing(h);
    setName(h.name);
    setHost(h.host);
    setEnabled(h.enabled);
    setError(null);
  };

  const save = async () => {
    const trimmedHost = host.trim().toLowerCase();
    if (!name.trim() || !trimmedHost) return;
    setError(null);
    try {
      if (editing) {
        await updateNetworkHost(editing.id, {
          name: name.trim(),
          host: trimmedHost,
          enabled,
        });
      } else {
        await createNetworkHost({
          name: name.trim(),
          host: trimmedHost,
          enabled,
        });
      }
      await queryClient.invalidateQueries({ queryKey: ["network-hosts"] });
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500">
        Friendly names for SMB hosts that are approved for network file imports.
        The deployment-wide allowlist is still enforced as a fallback.
      </p>

      <div className="rounded-md border border-slate-200 bg-white p-4">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
          <input
            type="text"
            placeholder="Friendly name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <input
            type="text"
            placeholder="hostname or IP"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Enabled
          </label>
          <button
            type="button"
            disabled={!name.trim() || !host.trim()}
            onClick={() => void save()}
            className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand/90 disabled:opacity-50"
          >
            {editing ? "Update" : "Add"}
          </button>
        </div>
        {editing && (
          <button
            type="button"
            onClick={resetForm}
            className="mt-2 text-sm text-slate-600 hover:text-slate-900"
          >
            Cancel edit
          </button>
        )}
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>

      <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
        {isLoading ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : hosts.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">No approved SMB hosts yet.</p>
        ) : (
          <table className="min-w-full divide-y divide-slate-200">
            <tbody className="divide-y divide-slate-100">
              {hosts.map((h) => (
                <tr key={h.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-sm font-medium text-slate-900">{h.name}</td>
                  <td className="px-4 py-3 text-sm font-mono text-slate-600">{h.host}</td>
                  <td className="px-4 py-3 text-sm text-slate-600">{h.enabled ? "Enabled" : "Disabled"}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => startEdit(h)}
                      className="mr-2 text-sm font-medium text-brand hover:underline"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (confirm("Remove this approved host?")) {
                          deleteMutation.mutate(h.id);
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
        )}
      </div>
    </div>
  );
}
