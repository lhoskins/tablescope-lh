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
} from "@/lib/api/repository-connectors";

const PAGE_SIZE = 25;

function classNames(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    active: "bg-emerald-50 text-emerald-700",
    disabled: "bg-slate-100 text-slate-500",
    error: "bg-red-50 text-red-700",
    queued: "bg-sky-50 text-sky-700",
    running: "bg-amber-50 text-amber-700",
    succeeded: "bg-emerald-50 text-emerald-700",
    partial: "bg-amber-50 text-amber-700",
    failed: "bg-red-50 text-red-700",
    pending: "bg-slate-100 text-slate-500",
    completed: "bg-emerald-50 text-emerald-700",
    governance_blocked: "bg-amber-50 text-amber-700",
    skipped: "bg-slate-100 text-slate-500",
  };
  const cls = styles[status] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={classNames("rounded-full px-2 py-0.5 text-xs font-medium", cls)}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export default function RepositoriesPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const connectionsQuery = useQuery({
    queryKey: ["repository-connections"],
    queryFn: listRepositoryConnections,
  });
  const typesQuery = useQuery({
    queryKey: ["repository-connector-types"],
    queryFn: listRepositoryConnectorTypes,
  });

  const selected = useMemo(
    () => connectionsQuery.data?.find((c) => c.id === selectedId) ?? null,
    [connectionsQuery.data, selectedId],
  );

  const createMutation = useMutation({
    mutationFn: createRepositoryConnection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repository-connections"] });
      setIsCreating(false);
    },
  });

  return (
    <section className="space-y-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Repositories</h1>
          <p className="mt-1 text-sm text-slate-500">
            Securely connect to UNC/SMB shares, scan metadata, and prepare file
            content for extraction.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setSelectedId(null);
            setIsCreating(true);
          }}
          className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand/90"
        >
          Add repository
        </button>
      </header>

      {connectionsQuery.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {connectionsQuery.error && (
        <p className="text-sm text-red-600">
          {(connectionsQuery.error as Error).message}
        </p>
      )}

      {connectionsQuery.data && connectionsQuery.data.length === 0 && !isCreating && (
        <p className="text-sm text-slate-500">
          No repository connectors configured yet.
        </p>
      )}

      {connectionsQuery.data && connectionsQuery.data.length > 0 && !isCreating && (
        <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-slate-500">
                  Last scan
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {connectionsQuery.data.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => {
                    setSelectedId(c.id);
                    setIsCreating(false);
                  }}
                  className={classNames(
                    "cursor-pointer hover:bg-slate-50",
                    selectedId === c.id && "bg-brand-50",
                  )}
                >
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-slate-900">{c.name}</div>
                    <div className="text-xs text-slate-400">{c.description}</div>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">
                    {c.connector_type}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500">
                    {c.last_successful_scan_at
                      ? new Date(c.last_successful_scan_at).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(isCreating || selected) && (
        <ConnectionForm
          connection={selected}
          connectorTypes={typesQuery.data ?? []}
          onCancel={() => {
            setIsCreating(false);
            setSelectedId(null);
          }}
          onCreate={(body) => createMutation.mutate(body)}
          onUpdate={(id, body) => updateRepositoryConnection(id, body)}
        />
      )}

      {selected && !isCreating && (
        <>
          <ConnectionDetail connection={selected} />
          <ScanHistory connection={selected} />
          <RepositoryProfile connection={selected} />
          <RepositoryItemsBrowser connection={selected} />
        </>
      )}
    </section>
  );
}

function ConnectionForm({
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

function ConnectionDetail({ connection }: { connection: RepositoryConnection }) {
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

function ScanHistory({ connection }: { connection: RepositoryConnection }) {
  const scansQuery = useQuery({
    queryKey: ["repository-scans", connection.id],
    queryFn: () => listRepositoryScans(connection.id),
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6">
      <h3 className="text-base font-semibold text-slate-900">Scan history</h3>
      {scansQuery.isLoading && <p className="mt-2 text-sm text-slate-500">Loading…</p>}
      {scansQuery.data && scansQuery.data.length === 0 && (
        <p className="mt-2 text-sm text-slate-500">No scans yet.</p>
      )}
      {scansQuery.data && scansQuery.data.length > 0 && (
        <table className="mt-3 min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Status
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Files
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Directories
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Added
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Changed
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Deleted
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                Completed
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {scansQuery.data.map((scan) => (
              <tr key={scan.id}>
                <td className="px-3 py-2">
                  <StatusBadge status={scan.status} />
                </td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.files_seen}</td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.directories_seen}</td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.added_count}</td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.changed_count}</td>
                <td className="px-3 py-2 text-sm text-slate-600">{scan.deleted_count}</td>
                <td className="px-3 py-2 text-sm text-slate-500">
                  {scan.completed_at ? new Date(scan.completed_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function RepositoryProfile({ connection }: { connection: RepositoryConnection }) {
  const profileQuery = useQuery({
    queryKey: ["repository-profile", connection.id],
    queryFn: () => getRepositoryProfile(connection.id),
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6">
      <h3 className="text-base font-semibold text-slate-900">Profile</h3>
      {profileQuery.isLoading && <p className="mt-2 text-sm text-slate-500">Loading…</p>}
      {profileQuery.data && (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label="Total files"
            value={Number(profileQuery.data.profile.total_files ?? 0)}
          />
          <StatCard
            label="Directories"
            value={Number(profileQuery.data.profile.total_directories ?? 0)}
          />
          <StatCard
            label="Total bytes"
            value={Number(profileQuery.data.profile.total_bytes ?? 0)}
          />
          <StatCard
            label="Duplicate candidates"
            value={Number(profileQuery.data.profile.duplicate_candidates ?? 0)}
          />
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-2xl font-semibold text-slate-900">{value.toLocaleString()}</div>
      <div className="mt-0.5 text-xs uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}

function RepositoryItemsBrowser({ connection }: { connection: RepositoryConnection }) {
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const itemsQuery = useQuery({
    queryKey: ["repository-items", connection.id, offset, search],
    queryFn: () =>
      listRepositoryItems(connection.id, { limit: PAGE_SIZE, offset, search }),
  });
  const totalPages = itemsQuery.data
    ? Math.max(1, Math.ceil(itemsQuery.data.total / PAGE_SIZE))
    : 1;
  const page = Math.floor(offset / PAGE_SIZE);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-900">Items</h3>
        <input
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
          }}
          placeholder="Search name or path…"
          className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        />
      </div>

      {itemsQuery.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {itemsQuery.data && itemsQuery.data.items.length === 0 && (
        <p className="text-sm text-slate-500">No items found.</p>
      )}

      {itemsQuery.data && itemsQuery.data.items.length > 0 && (
        <>
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                  Name
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                  Type
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                  Size
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase text-slate-500">
                  Extraction
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {itemsQuery.data.items.map((item: RepositoryItem) => (
                <tr key={item.id}>
                  <td className="px-3 py-2 text-sm text-slate-900">{item.name}</td>
                  <td className="px-3 py-2 text-sm text-slate-600">{item.item_type}</td>
                  <td className="px-3 py-2 text-sm text-slate-600">
                    {item.size != null ? item.size.toLocaleString() : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge status={item.extraction_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
            <span>
              {offset + 1}–
              {Math.min(offset + PAGE_SIZE, itemsQuery.data.total)} of{" "}
              {itemsQuery.data.total}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                disabled={page === 0}
                className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() =>
                  setOffset((o) =>
                    Math.min((totalPages - 1) * PAGE_SIZE, o + PAGE_SIZE),
                  )
                }
                disabled={page >= totalPages - 1}
                className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
