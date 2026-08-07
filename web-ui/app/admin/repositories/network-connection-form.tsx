"use client";

import { useState } from "react";
import {
  createNetworkFileConnection,
  testNetworkFileConnection,
  updateNetworkFileConnection,
  type NetworkFileConnection,
  type NetworkFileConnectionCreate,
} from "@/lib/api/network-file-connections";

const emptyForm: NetworkFileConnectionCreate = {
  name: "",
  host: "",
  share_name: "",
  approved_root_path: "",
  port: 445,
  domain: "",
  username: "",
  password: "",
  require_signing: true,
  require_encryption: true,
  enabled: true,
};

export function NetworkConnectionForm({
  connection,
  onDone,
  onCancel,
}: {
  connection?: NetworkFileConnection | null;
  onDone: (conn: NetworkFileConnection) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<NetworkFileConnectionCreate>({
    ...emptyForm,
    name: connection?.name ?? "",
    host: connection?.host ?? "",
    share_name: connection?.share_name ?? "",
    approved_root_path: connection?.approved_root_path ?? "",
    port: connection?.port ?? 445,
    domain: connection?.domain ?? "",
    username: connection?.username ?? "",
    password: "",
    require_signing: connection?.require_signing ?? true,
    require_encryption: connection?.require_encryption ?? true,
    enabled: connection?.enabled ?? true,
  });
  const [testing, setTesting] = useState(false);
  const [testMessage, setTestMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSave = form.name && form.host && form.share_name;

  const update = <K extends keyof NetworkFileConnectionCreate>(
    key: K,
    value: NetworkFileConnectionCreate[K],
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const test = async () => {
    if (!connection) return;
    setTesting(true);
    setTestMessage(null);
    setError(null);
    try {
      const res = await testNetworkFileConnection(connection.id);
      setTestMessage(res.ok ? "Connection succeeded." : res.message ?? "Connection check failed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection test failed.");
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const payload: NetworkFileConnectionCreate = {
        ...form,
        host: form.host.trim().toLowerCase(),
        share_name: form.share_name.trim(),
        approved_root_path: form.approved_root_path?.trim() ?? "",
      };
      const conn = connection
        ? await updateNetworkFileConnection(connection.id, payload)
        : await createNetworkFileConnection(payload);
      onDone(conn);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save connection.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4 rounded-md border border-slate-200 bg-white p-4">
      <h3 className="text-lg font-medium text-slate-900">
        {connection ? "Edit network file connection" : "Add network file connection"}
      </h3>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label className="block text-sm font-medium text-slate-700">Name</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => update("name", e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            placeholder="Customer repository"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">Host or IP</label>
          <input
            type="text"
            value={form.host}
            onChange={(e) => update("host", e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            placeholder="10.250.10.229"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">Port</label>
          <input
            type="number"
            value={form.port}
            onChange={(e) => update("port", parseInt(e.target.value, 10) || 445)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">Share name</label>
          <input
            type="text"
            value={form.share_name}
            onChange={(e) => update("share_name", e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            placeholder="repository"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">Approved root path</label>
          <input
            type="text"
            value={form.approved_root_path}
            onChange={(e) => update("approved_root_path", e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            placeholder="finance/q3 (optional)"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">Domain</label>
          <input
            type="text"
            value={form.domain}
            onChange={(e) => update("domain", e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            placeholder="WORKGROUP"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">Username</label>
          <input
            type="text"
            value={form.username}
            onChange={(e) => update("username", e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">
            {connection?.has_secret ? "New password (leave blank to keep)" : "Password"}
          </label>
          <input
            type="password"
            value={form.password}
            onChange={(e) => update("password", e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.require_signing}
            onChange={(e) => update("require_signing", e.target.checked)}
          />
          Require SMB signing
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.require_encryption}
            onChange={(e) => update("require_encryption", e.target.checked)}
          />
          Require SMB encryption
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => update("enabled", e.target.checked)}
          />
          Enabled
        </label>
      </div>

      {testMessage && (
        <p className={`text-sm ${testMessage.includes("succeeded") ? "text-green-600" : "text-amber-600"}`}>
          {testMessage}
        </p>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex gap-2">
        {connection && (
          <button
            type="button"
            onClick={() => void test()}
            disabled={testing}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {testing ? "Testing…" : "Test connection"}
          </button>
        )}
        <button
          type="button"
          onClick={() => void save()}
          disabled={!canSave || saving}
          className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand/90 disabled:opacity-50"
        >
          {saving ? "Saving…" : connection ? "Save changes" : "Add connection"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-600 hover:text-slate-900"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
