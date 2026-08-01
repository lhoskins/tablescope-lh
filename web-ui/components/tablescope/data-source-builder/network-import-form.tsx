"use client";

import { useState } from "react";
import { IconLock, IconServer } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  importFromNetwork,
  testNetworkPath,
  type ImportCapabilities,
} from "@/lib/api/data-source-builder";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { ImportProgress } from "./import-progress";
import { sessionSourceFromPreview, type ImportStage } from "./import-source";

/** Show only the file name; intermediate folders can be sensitive. */
function fileNameOf(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length > 1 ? parts[parts.length - 1] : "";
}

export function NetworkImportForm({
  connections,
  onImported,
}: {
  connections: ImportCapabilities["network_connections"];
  onImported?: () => void;
}) {
  const addSource = useBuilderStore((s) => s.addSource);
  const markCreated = useBuilderStore((s) => s.markCreated);

  const [connectionId, setConnectionId] = useState<number | null>(
    connections[0]?.id ?? null,
  );
  const [path, setPath] = useState("");
  const [stage, setStage] = useState<ImportStage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  const trimmed = path.trim();
  const looksLikePath =
    trimmed.startsWith("\\\\") || trimmed.toLowerCase().startsWith("smb://");
  const ready = connectionId !== null && looksLikePath && Boolean(fileNameOf(trimmed));

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

  return (
    <div>
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
          <label
            htmlFor="import-network-connection"
            className="block text-caption font-medium text-ink-secondary"
          >
            Saved credential
          </label>
          <select
            id="import-network-connection"
            value={connectionId ?? ""}
            onChange={(e) => setConnectionId(Number(e.target.value))}
            className="mt-1 w-full rounded-lg border border-line-secondary bg-bg-primary px-3 py-2 text-[13px] text-ink-primary outline-none focus:border-brand-100 focus:ring-2 focus:ring-brand-100"
          >
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.label})
              </option>
            ))}
          </select>
        </div>
      </div>

      {trimmed && !looksLikePath && (
        <p className="mt-1.5 text-caption text-danger">
          Use a UNC path (\\server\share\file) or an smb:// URL.
        </p>
      )}
      {testResult && (
        <p className="mt-1.5 text-caption text-success">{testResult}</p>
      )}

      <div className="mt-3 flex gap-2">
        <Button
          variant="secondary"
          disabled={connectionId === null}
          onClick={() => void test()}
        >
          Test access
        </Button>
        <Button variant="primary" disabled={!ready} onClick={() => void run()}>
          Import &amp; analyze
        </Button>
      </div>

      <ImportProgress
        stage={stage}
        error={error}
        onRetry={() => setStage("idle")}
      />

      <p className="mt-2 flex items-start gap-1.5 text-caption text-ink-tertiary">
        <IconLock size={13} className="mt-0.5 shrink-0" />
        Credentials stay on the server. Tablescope reads the file once over an
        encrypted SMB session and keeps a snapshot; your browser never touches
        the share.
      </p>
    </div>
  );
}
