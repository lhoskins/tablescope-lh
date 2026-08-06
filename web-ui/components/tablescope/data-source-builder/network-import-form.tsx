"use client";

import { useState } from "react";
import { IconFolder, IconLock, IconServer } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  browseNetworkConnection,
  importFromNetwork,
  testNetworkPath,
  type ImportCapabilities,
  type NetworkFileEntry,
} from "@/lib/api/data-source-builder";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { ImportProgress } from "./import-progress";
import { sessionSourceFromPreview, type ImportStage } from "./import-source";

/** Show only the file name; intermediate folders can be sensitive. */
function fileNameOf(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length > 1 ? parts[parts.length - 1] : "";
}

/** Build a full UNC from a connection label and a share-relative entry path. */
function uncPath(label: string, relativePath: string): string {
  const root = label.replace(/\\+$/, "");
  const tail = relativePath.replace(/\//g, "\\");
  return `${root}\\${tail}`;
}

export function NetworkImportForm({
  connections,
  hosts,
  onImported,
}: {
  connections: ImportCapabilities["network_connections"];
  hosts: ImportCapabilities["network_hosts"];
  onImported?: () => void;
}) {
  const addSource = useBuilderStore((s) => s.addSource);
  const markCreated = useBuilderStore((s) => s.markCreated);

  const [connectionId, setConnectionId] = useState<number | null>(
    connections[0]?.id ?? null,
  );
  const [view, setView] = useState<"cards" | "browse" | "manual">("cards");
  const [path, setPath] = useState("");
  const [stage, setStage] = useState<ImportStage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [entries, setEntries] = useState<NetworkFileEntry[]>([]);
  const [browsePath, setBrowsePath] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const connection = connections.find((c) => c.id === connectionId);
  const trimmed = path.trim();
  const looksLikePath =
    trimmed.startsWith("\\\\") || trimmed.toLowerCase().startsWith("smb://");
  const ready = connectionId !== null && looksLikePath && Boolean(fileNameOf(trimmed));

  const hostFor = (hostName?: string) =>
    hosts.find((h) => h.host === hostName?.toLowerCase()) ??
    hosts.find((h) => h.name.toLowerCase() === hostName?.toLowerCase());

  if (connections.length === 0) {
    return (
      <p className="text-small text-ink-tertiary">
        No approved network locations yet. An administrator adds them under
        Settings → Network file connections before network import can be used.
      </p>
    );
  }

  const test = async () => {
    if (connectionId === null) return;
    setError(null);
    setTestResult(null);
    try {
      const res = await testNetworkPath(connectionId, trimmed || undefined);
      setTestResult(res.ok ? "Access confirmed." : "Access could not be confirmed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Access test failed.");
    }
  };

  const run = async () => {
    if (connectionId === null) return;
    setError(null);
    setTestResult(null);
    setStage("connecting");
    try {
      setStage("transferring");
      const preview = await importFromNetwork(connectionId, trimmed);
      setStage("profiling");
      const source = sessionSourceFromPreview(preview);
      addSource(source);
      markCreated([source.id]);
      setStage("ready");
      setPath("");
      setView("cards");
      onImported?.();
    } catch (err) {
      setStage("error");
      setError(
        err instanceof Error
          ? err.message
          : "That file could not be imported from the network location.",
      );
    }
  };

  const startBrowse = async (id: number) => {
    setConnectionId(id);
    setView("browse");
    setLoading(true);
    setError(null);
    try {
      const res = await browseNetworkConnection(id);
      setEntries(res.entries);
      setBrowsePath(res.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Browse failed.");
      setView("cards");
    } finally {
      setLoading(false);
    }
  };

  const openFolder = async (entry: NetworkFileEntry) => {
    if (!connectionId || !connection) return;
    setLoading(true);
    setError(null);
    try {
      const fullPath = uncPath(connection.label, entry.path);
      const res = await browseNetworkConnection(connectionId, fullPath);
      setEntries(res.entries);
      setBrowsePath(res.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Browse failed.");
    } finally {
      setLoading(false);
    }
  };

  const pickFile = (entry: NetworkFileEntry) => {
    if (!connection) return;
    setPath(uncPath(connection.label, entry.path));
    setView("manual");
  };

  if (view === "manual" && connection) {
    return (
      <div className="space-y-3">
        <button
          type="button"
          onClick={() => setView("cards")}
          className="text-caption text-ink-tertiary hover:text-ink-primary"
        >
          ← Back to network connections
        </button>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
          <div>
            <label
              htmlFor="import-network-path"
              className="block text-caption font-medium text-ink-secondary"
            >
              Network path
            </label>
            <div className="mt-1 flex items-center gap-2 rounded-lg border border-line-secondary bg-bg-primary px-3 py-2 focus-within:border-brand-100 focus-within:ring-2 focus-within:ring-brand-100">
              <IconServer size={16} className="shrink-0 text-ink-tertiary" />
              <input
                id="import-network-path"
                type="text"
                autoComplete="off"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="\\fileserver\finance\q3\sales.xlsx"
                className="min-w-0 flex-1 bg-transparent font-mono text-[13px] text-ink-primary outline-none placeholder:text-ink-tertiary"
              />
            </div>
          </div>
          <div>
            <label className="block text-caption font-medium text-ink-secondary">
              Saved credential
            </label>
            <p className="mt-1 rounded-lg border border-line-secondary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary">
              {connection.name}
            </p>
          </div>
        </div>
        {trimmed && !looksLikePath && (
          <p className="text-caption text-danger">
            Use a UNC path (\\server\share\file) or an smb:// URL.
          </p>
        )}
        {testResult && <p className="text-caption text-success">{testResult}</p>}
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => void test()}>
            Test access
          </Button>
          <Button variant="primary" disabled={!ready} onClick={() => void run()}>
            Import &amp; analyze
          </Button>
        </div>
        <ImportProgress stage={stage} error={error} onRetry={() => setStage("idle")} />
        <p className="flex items-start gap-1.5 text-caption text-ink-tertiary">
          <IconLock size={13} className="mt-0.5 shrink-0" />
          Credentials stay on the server. Tablescope reads the file once over an
          encrypted SMB session and keeps a snapshot.
        </p>
      </div>
    );
  }

  if (view === "browse" && connection) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => setView("cards")}
            className="text-caption text-ink-tertiary hover:text-ink-primary"
          >
            ← Back
          </button>
          <p className="text-caption text-ink-tertiary font-mono truncate max-w-[60%]">
            {browsePath}
          </p>
        </div>
        {loading ? (
          <p className="text-small text-ink-tertiary">Loading…</p>
        ) : entries.length === 0 ? (
          <p className="text-small text-ink-tertiary">This folder is empty.</p>
        ) : (
          <ul className="max-h-72 overflow-y-auto rounded-lg border border-line-tertiary">
            {entries.map((entry) => (
              <li
                key={entry.path}
                className="flex items-center justify-between border-b border-line-tertiary px-3 py-2 last:border-b-0 hover:bg-bg-secondary/50"
              >
                <button
                  type="button"
                  onClick={() =>
                    entry.kind === "directory" ? openFolder(entry) : pickFile(entry)
                  }
                  className="flex items-center gap-2 text-[13px] text-ink-primary"
                >
                  <IconFolder
                    size={16}
                    className={
                      entry.kind === "directory"
                        ? "text-brand-500"
                        : "text-ink-tertiary"
                    }
                  />
                  {entry.name}
                </button>
                {entry.kind === "file" && (
                  <Button variant="primary" size="sm" onClick={() => pickFile(entry)}>
                    Import
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {error && <p className="text-caption text-danger">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {connections.map((c) => {
          const friendly = hostFor(c.label);
          return (
            <div
              key={c.id}
              className="rounded-lg border border-line-tertiary p-3 transition-colors hover:border-brand-200"
            >
              <div className="flex items-start gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-bg-tertiary text-ink-tertiary">
                  <IconServer size={17} />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-semibold text-ink-primary">
                    {c.name}
                  </p>
                  <p className="truncate text-caption text-ink-tertiary font-mono">
                    {c.label}
                  </p>
                  {friendly && (
                    <p className="truncate text-caption text-success">
                      {friendly.name}
                    </p>
                  )}
                </div>
              </div>
              <div className="mt-3 flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setConnectionId(c.id);
                    setPath("");
                    setView("manual");
                  }}
                >
                  Enter path
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => void startBrowse(c.id)}
                >
                  Browse
                </Button>
              </div>
            </div>
          );
        })}
      </div>
      {error && <p className="text-caption text-danger">{error}</p>}
      <p className="flex items-start gap-1.5 text-caption text-ink-tertiary">
        <IconLock size={13} className="mt-0.5 shrink-0" />
        Credentials stay on the server. Tablescope reads the file once over an
        encrypted SMB session and keeps a snapshot.
      </p>
    </div>
  );
}
