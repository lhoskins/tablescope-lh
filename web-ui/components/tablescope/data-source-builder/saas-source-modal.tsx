"use client";

import { useEffect, useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { IconCheck, IconLoader2, IconSearch, IconX } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  listSaaSFields,
  listSaaSObjects,
  type SaasObject,
} from "@/lib/api/data-source-builder";
import type { SaasCredential } from "@/lib/api/connectors";
import {
  useBuilderStore,
  type SessionSource,
  type SourceType,
} from "@/lib/stores/data-source-builder-store";
import { BrandLogo, connectorChip } from "../database-connectors/brand-logo";

export function SaaSSourceModal({
  credential,
  onClose,
}: {
  credential: SaasCredential;
  onClose: () => void;
}) {
  const [objects, setObjects] = useState<SaasObject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");

  const { sources, addSource, markCreated } = useBuilderStore(
    useShallow((s) => ({
      sources: s.sources,
      addSource: s.addSource,
      markCreated: s.markCreated,
    })),
  );
  const existingNames = useMemo(
    () =>
      new Set(
        sources
          .filter(
            (src) =>
              src.isSaaS &&
              src.connectionConfig.credential_id === String(credential.id),
          )
          .flatMap((src) => src.tables.map((t) => t.tableName)),
      ),
    [sources, credential.id],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listSaaSObjects(credential.id)
      .then((res) => {
        if (!cancelled) setObjects(res);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Could not load objects");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [credential.id]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return objects;
    return objects.filter(
      (o) =>
        o.name.toLowerCase().includes(term) ||
        o.label.toLowerCase().includes(term),
    );
  }, [objects, search]);

  const toggle = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleCreate = async () => {
    if (selected.size === 0) return;
    setCreating(true);
    setError(null);
    try {
      const selectedObjects = objects.filter((o) => selected.has(o.name));
      for (const object of selectedObjects) {
        const fields = await listSaaSFields(credential.id, object.name);
        const fieldNames = fields.map((f) => f.name);
        const sourceId = `saas-${credential.id}-${object.name}-${Date.now()}`;
        const source: SessionSource = {
          id: sourceId,
          sourceType: credential.connector_type as SourceType,
          displayName: `${credential.display_name} · ${object.label || object.name}`,
          connectionConfig: {
            credential_id: String(credential.id),
            connector_type: credential.connector_type,
          },
          status: "ready",
          isFileUpload: false,
          isSaaS: true,
          selectedFields: fieldNames,
          tables: [
            {
              tableName: object.name,
              rows: 0,
              cols: fieldNames.length,
              aiEnabled: true,
              state: "adding",
            },
          ],
        };
        addSource(source);
        markCreated([`${sourceId}::${object.name}`]);
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create source");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl bg-bg-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line-tertiary px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${connectorChip(
                credential.connector_type,
              )}`}
            >
              <BrandLogo connector={credential.connector_type} size={20} />
            </span>
            <div>
              <h2 className="text-h3 text-ink-primary">Select objects</h2>
              <p className="text-caption text-ink-tertiary">
                Choose objects from {credential.display_name} to create as data
                sources.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-7 w-7 items-center justify-center rounded text-ink-tertiary hover:bg-bg-secondary"
          >
            <IconX size={16} />
          </button>
        </div>

        <div className="px-4 py-3">
          <div className="relative">
            <IconSearch
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-tertiary"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search objects…"
              className="h-9 w-full rounded-md border border-line-secondary bg-bg-primary pl-8 pr-3 text-[13px] text-ink-primary placeholder:text-ink-tertiary focus:border-brand-500 focus:outline-none"
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-small text-ink-tertiary">
              <IconLoader2 size={15} className="animate-spin" /> Loading
              objects…
            </div>
          ) : filtered.length === 0 ? (
            <p className="py-12 text-center text-small text-ink-tertiary">
              {objects.length === 0
                ? "No objects found for this connector."
                : `No objects match "${search}".`}
            </p>
          ) : (
            <div className="space-y-1 pb-4">
              {filtered.map((object) => {
                const isSelected = selected.has(object.name);
                const already = existingNames.has(object.name);
                return (
                  <button
                    key={object.name}
                    type="button"
                    onClick={() => !already && toggle(object.name)}
                    disabled={already}
                    className={`flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-left ${
                      isSelected
                        ? "border-brand-500 bg-brand-50/30"
                        : "border-line-tertiary bg-bg-primary hover:bg-bg-secondary"
                    } ${already ? "opacity-60" : ""}`}
                  >
                    <div>
                      <p className="text-[13px] font-medium text-ink-primary">
                        {object.label || object.name}
                      </p>
                      <p className="text-caption text-ink-tertiary">
                        {object.name}
                      </p>
                    </div>
                    <span
                      className={`flex h-5 w-5 items-center justify-center rounded border ${
                        isSelected
                          ? "border-brand-500 bg-brand-500 text-white"
                          : "border-line-secondary"
                      }`}
                    >
                      {isSelected && <IconCheck size={12} />}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {error && (
          <div className="border-t border-line-tertiary px-4 py-2 text-[12px] text-danger">
            {error}
          </div>
        )}

        <div className="flex items-center justify-between border-t border-line-tertiary px-4 py-3">
          <span className="text-[12px] text-ink-secondary">
            {selected.size} selected
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={onClose} disabled={creating}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleCreate}
              disabled={creating || selected.size === 0}
            >
              {creating && (
                <IconLoader2 size={14} className="animate-spin" />
              )}
              Create {selected.size || ""} data source
              {selected.size === 1 ? "" : "s"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
