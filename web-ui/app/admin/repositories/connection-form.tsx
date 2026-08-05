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



export function ConnectionForm({
  connection,
  connectorTypes,
  onCancel,
  onCreate,
  onUpdate,
}: {
  connection: RepositoryConnection | null;
  connectorTypes: { connector_type: string; name: string }[];
  onCancel: () => void;
  onCreate: (body: RepositoryConnectionCreate) => void;
  onUpdate: (id: number, body: RepositoryConnectionUpdate) => Promise<RepositoryConnection>;
}) {
  const queryClient = useQueryClient();
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  const [form, setForm] = useState({
    name: connection?.name ?? "",
    description: connection?.description ?? "",
    connector_type: connection?.connector_type ?? "unc",
    rootPath: (connection?.config.rootPath as string) ?? "",
    allowedSubpath: (connection?.config.allowedSubpath as string) ?? "",
    allowedExtensions: (connection?.config.allowedExtensions as string[])?.join(", ") ?? "",
    includePatterns: (connection?.config.includePatterns as string[])?.join(", ") ?? "",
    excludePatterns: (connection?.config.excludePatterns as string[])?.join(", ") ?? "",
    maxFileSizeBytes: String(connection?.config.maxFileSizeBytes ?? ""),
    recursive: (connection?.config.recursive as boolean | undefined) ?? true,
    smbEncryption: (connection?.config.smbEncryption as boolean | undefined) ?? false,
    smbSigning: (connection?.config.smbSigning as boolean | undefined) ?? true,
    domain: "",
    username: "",
    password: "",
    expected_version: connection?.version ?? 0,
  });

  const isEdit = Boolean(connection);

  const testConfig = useMutation({
    mutationFn: async () => {
      const config = buildConfig();
      const result = await testRepositoryConnectionConfig({
        name: form.name,
        connector_type: form.connector_type,
        config,
        secret: buildSecret(),
      });
      return result;
    },
    onSuccess: (result) => {
      const failed = result.checks.find((c) => c.status === "failed");
      setTestResult({
        success: result.success,
        message: failed?.message ?? (result.success ? "Connection test passed" : "Connection test failed"),
      });
    },
    onError: (err) => {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Test failed",
      });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (body: RepositoryConnectionUpdate) =>
      onUpdate(connection!.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repository-connections"] });
    },
  });

  function buildConfig() {
    return {
      rootPath: form.rootPath,
      allowedSubpath: form.allowedSubpath,
      allowedExtensions: form.allowedExtensions
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      includePatterns: form.includePatterns
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      excludePatterns: form.excludePatterns
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      maxFileSizeBytes: form.maxFileSizeBytes ? Number(form.maxFileSizeBytes) : undefined,
      recursive: form.recursive,
      smbEncryption: form.smbEncryption,
      smbSigning: form.smbSigning,
    };
  }

  function buildSecret() {
    const secret: Record<string, string> = {};
    if (form.domain) secret.domain = form.domain;
    if (form.username) secret.username = form.username;
    if (form.password) secret.password = form.password;
    return secret;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const payload: RepositoryConnectionCreate = {
      name: form.name,
      description: form.description || undefined,
      connector_type: form.connector_type,
      config: buildConfig(),
      secret: buildSecret(),
    };
    if (isEdit) {
      updateMutation.mutate({ ...payload, expected_version: form.expected_version });
    } else {
      onCreate(payload);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="text-lg font-semibold text-slate-900">
        {isEdit ? "Edit repository" : "New repository"}
      </h2>
      <form onSubmit={handleSubmit} className="mt-4 space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="flex flex-col text-xs text-slate-500">
            Name
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
              required
            />
          </label>
          <label className="flex flex-col text-xs text-slate-500">
            Connector type
            <select
              value={form.connector_type}
              onChange={(e) =>
                setForm((f) => ({ ...f, connector_type: e.target.value }))
              }
              className="mt-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            >
              {connectorTypes.map((t) => (
                <option key={t.connector_type} value={t.connector_type}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="flex flex-col text-xs text-slate-500">
          UNC root path
          <input
            type="text"
            value={form.rootPath}
            onChange={(e) => setForm((f) => ({ ...f, rootPath: e.target.value }))}
            placeholder="\\\\server\\share"
            className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
            required
          />
        </label>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="flex flex-col text-xs text-slate-500">
            Allowed subpath
            <input
              type="text"
              value={form.allowedSubpath}
              onChange={(e) =>
                setForm((f) => ({ ...f, allowedSubpath: e.target.value }))
              }
              placeholder="Reports/2026"
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
            />
          </label>
          <label className="flex flex-col text-xs text-slate-500">
            Allowed extensions
            <input
              type="text"
              value={form.allowedExtensions}
              onChange={(e) =>
                setForm((f) => ({ ...f, allowedExtensions: e.target.value }))
              }
              placeholder="pdf, docx, xlsx"
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
            />
          </label>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="flex flex-col text-xs text-slate-500">
            Domain
            <input
              type="text"
              value={form.domain}
              onChange={(e) => setForm((f) => ({ ...f, domain: e.target.value }))}
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
            />
          </label>
          <label className="flex flex-col text-xs text-slate-500">
            Username
            <input
              type="text"
              value={form.username}
              onChange={(e) =>
                setForm((f) => ({ ...f, username: e.target.value }))
              }
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
            />
          </label>
        </div>

        <label className="flex flex-col text-xs text-slate-500">
          Password
          <input
            type="password"
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            placeholder="Stored encrypted; only fill to set or rotate"
            className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
          />
        </label>

        <details className="text-sm text-slate-600">
          <summary className="cursor-pointer text-brand-600 hover:underline">
            Advanced options
          </summary>
          <div className="mt-3 space-y-3">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className="flex flex-col text-xs text-slate-500">
                Include patterns
                <input
                  type="text"
                  value={form.includePatterns}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, includePatterns: e.target.value }))
                  }
                  placeholder="Reports/**/*.pdf"
                  className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
                />
              </label>
              <label className="flex flex-col text-xs text-slate-500">
                Exclude patterns
                <input
                  type="text"
                  value={form.excludePatterns}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, excludePatterns: e.target.value }))
                  }
                  placeholder="**/*.tmp"
                  className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
                />
              </label>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <label className="flex flex-col text-xs text-slate-500">
                Max file size (bytes)
                <input
                  type="number"
                  value={form.maxFileSizeBytes}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, maxFileSizeBytes: e.target.value }))
                  }
                  className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900"
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={form.recursive}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, recursive: e.target.checked }))
                  }
                />
                Recursive scan
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={form.smbEncryption}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, smbEncryption: e.target.checked }))
                  }
                />
                SMB encryption
              </label>
            </div>
          </div>
        </details>

        {testResult && (
          <div
            className={classNames(
              "rounded-md px-3 py-2 text-sm",
              testResult.success
                ? "bg-emerald-50 text-emerald-700"
                : "bg-red-50 text-red-700",
            )}
          >
            {testResult.message}
          </div>
        )}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={updateMutation.isPending}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand/90 disabled:opacity-50"
          >
            {isEdit ? "Save changes" : "Create repository"}
          </button>
          <button
            type="button"
            onClick={() => testConfig.mutate()}
            disabled={testConfig.isPending}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Test connection
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}