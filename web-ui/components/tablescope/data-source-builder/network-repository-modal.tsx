"use client";

import { useEffect, useState } from "react";
import { IconFolder, IconLoader2, IconServer } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  browseNetworkConnection,
  importFromNetwork,
  type NetworkFileConnection,
  type NetworkFileEntry,
} from "@/lib/api/data-source-builder";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { sessionSourceFromPreview } from "./import-source";

function uncPath(label: string, relativePath: string): string {
  const root = label.replace(/\\+$/, "");
  const tail = relativePath.replace(/\//g, "\\");
  return `${root}\\${tail}`;
}

export function NetworkRepositoryModal({
  connection,
  onClose,
}: {
  connection: NetworkFileConnection;
  onClose: () => void;
}) {
  const addSource = useBuilderStore((s) => s.addSource);
  const markCreated = useBuilderStore((s) => s.markCreated);

  const [entries, setEntries] = useState<NetworkFileEntry[]>([]);
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    browseNetworkConnection(connection.id)
      .then((res) => {
        setEntries(res.entries);
        setCurrentPath(res.path);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Browse failed."))
      .finally(() => setLoading(false));
  }, [connection.id]);

  const openFolder = async (entry: NetworkFileEntry) => {
    setLoading(true);
    setError(null);
    try {
      const fullPath = uncPath(connection.label, entry.path);
      const res = await browseNetworkConnection(connection.id, fullPath);
      setEntries(res.entries);
      setCurrentPath(res.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Browse failed.");
    } finally {
      setLoading(false);
    }
  };

  const pickFile = async (entry: NetworkFileEntry) => {
    setImporting(true);
    setError(null);
    try {
      const fullPath = uncPath(connection.label, entry.path);
      const preview = await importFromNetwork(connection.id, fullPath);
      const source = sessionSourceFromPreview(preview);
      addSource(source);
      markCreated([source.id]);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-xl border border-line-tertiary bg-bg-primary p-5 shadow-lg">
        <div className="mb-3 flex items-center gap-2">
          <IconServer size={18} className="text-brand-500" />
          <h3 className="text-h3 text-ink-primary">{connection.name}</h3>
        </div>
        <p className="truncate text-small text-ink-tertiary font-mono">
          {currentPath}
        </p>

        <div className="mt-3 max-h-72 overflow-y-auto rounded-lg border border-line-tertiary">
          {loading ? (
            <div className="flex items-center gap-2 p-4 text-small text-ink-tertiary">
              <IconLoader2 size={15} className="animate-spin" /> Loading…
            </div>
          ) : entries.length === 0 ? (
            <p className="p-4 text-small text-ink-tertiary">This folder is empty.</p>
          ) : (
            <ul className="divide-y divide-line-tertiary">
              {entries.map((entry) => (
                <li
                  key={entry.path}
                  className="flex items-center justify-between px-3 py-2 hover:bg-bg-secondary/50"
                >
                  <button
                    type="button"
                    onClick={() =>
                      entry.kind === "directory" ? openFolder(entry) : undefined
                    }
                    disabled={importing}
                    className="flex min-w-0 items-center gap-2 text-[13px] text-ink-primary"
                  >
                    <IconFolder
                      size={16}
                      className={
                        entry.kind === "directory"
                          ? "text-brand-500"
                          : "text-ink-tertiary"
                      }
                    />
                    <span className="truncate">{entry.name}</span>
                  </button>
                  {entry.kind === "file" && (
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={importing}
                      onClick={() => void pickFile(entry)}
                    >
                      {importing ? (
                        <IconLoader2 size={14} className="animate-spin" />
                      ) : (
                        "Import"
                      )}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {error && <p className="mt-2 text-caption text-danger">{error}</p>}

        <div className="mt-4 flex justify-end">
          <Button variant="secondary" onClick={onClose} disabled={importing}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}
