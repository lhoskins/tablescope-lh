"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { IconPencil, IconShield, IconTrash } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  createNetworkHost,
  deleteNetworkHost,
  listNetworkHosts,
  updateNetworkHost,
  type NetworkHost,
} from "@/lib/api/data-source-builder";

export function NetworkSecurityPanel() {
  const queryClient = useQueryClient();
  const { data: hosts = [], isLoading } = useQuery({
    queryKey: ["builder", "network-hosts"],
    queryFn: listNetworkHosts,
  });

  const [editing, setEditing] = useState<NetworkHost | null>(null);
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    const trimmed = host.trim().toLowerCase();
    if (!name.trim() || !trimmed) return;
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await updateNetworkHost(editing.id, {
          name: name.trim(),
          host: trimmed,
          enabled,
        });
      } else {
        await createNetworkHost({
          name: name.trim(),
          host: trimmed,
          enabled,
        });
      }
      await queryClient.invalidateQueries({
        queryKey: ["builder", "network-hosts"],
      });
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Remove this approved host?")) return;
    await deleteNetworkHost(id);
    await queryClient.invalidateQueries({
      queryKey: ["builder", "network-hosts"],
    });
  };

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-line-tertiary p-4">
        <div className="flex items-center gap-2">
          <IconShield size={18} className="text-brand-600" />
          <h3 className="text-h3 text-ink-primary">Approved SMB hosts</h3>
        </div>
        <p className="mt-0.5 text-small text-ink-tertiary">
          Hosts added here can be used by network file connections. The
          deployment-wide allowlist is always enforced as a fallback.
        </p>

        <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
          <input
            type="text"
            placeholder="Friendly name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded-lg border border-line-secondary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary outline-none focus:border-brand-100 focus:ring-2 focus:ring-brand-100"
          />
          <input
            type="text"
            placeholder="hostname or IP"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            className="rounded-lg border border-line-secondary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary outline-none focus:border-brand-100 focus:ring-2 focus:ring-brand-100"
          />
          <label className="flex items-center gap-2 text-small text-ink-secondary">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-line-secondary"
            />
            Enabled
          </label>
          <Button
            variant="primary"
            disabled={!name.trim() || !host.trim() || saving}
            onClick={() => void save()}
          >
            {editing ? "Update" : "Add"}
          </Button>
        </div>
        {editing && (
          <button
            type="button"
            onClick={resetForm}
            className="mt-2 text-caption text-ink-tertiary hover:text-ink-primary"
          >
            Cancel edit
          </button>
        )}
        {error && <p className="mt-2 text-caption text-danger">{error}</p>}
      </div>

      <div className="rounded-xl border border-line-tertiary p-0">
        {isLoading ? (
          <p className="p-4 text-small text-ink-tertiary">Loading…</p>
        ) : hosts.length === 0 ? (
          <p className="p-4 text-small text-ink-tertiary">
            No approved SMB hosts yet. Add one above to enable network file
            imports from that server.
          </p>
        ) : (
          <ul className="divide-y divide-line-tertiary">
            {hosts.map((h) => (
              <li
                key={h.id}
                className="flex items-center justify-between p-3"
              >
                <div>
                  <p className="text-[13px] font-semibold text-ink-primary">
                    {h.name}
                  </p>
                  <p className="text-caption text-ink-tertiary font-mono">
                    {h.host}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-caption ${
                      h.enabled
                        ? "bg-success/10 text-success"
                        : "bg-bg-tertiary text-ink-tertiary"
                    }`}
                  >
                    {h.enabled ? "Enabled" : "Disabled"}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => startEdit(h)}
                    aria-label="Edit"
                  >
                    <IconPencil size={16} />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void remove(h.id)}
                    aria-label="Delete"
                  >
                    <IconTrash size={16} className="text-danger" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
