"use client";

import { useEffect } from "react";
import type { PreflightResponse } from "@/lib/api/data-source-versions";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-0.5">
      <dt className="text-ink-tertiary">{label}</dt>
      <dd className="truncate text-right text-ink-primary">{value}</dd>
    </div>
  );
}

/**
 * "Update data source" preflight. Dropping (or picking) a file only ever gets
 * this far: the staged version is activated after an explicit confirmation, and
 * blocking schema changes disable confirmation entirely.
 */
export function DataSourceUpdateDialog({
  open,
  sourceName,
  preflight,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  sourceName: string;
  preflight: PreflightResponse | null;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;
  const compat = preflight?.compatibility;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-16"
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Update data source"
        className="w-full max-w-lg rounded-xl bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-ink-primary">
          Update data source
        </h3>
        <p className="mt-0.5 text-small text-ink-secondary">
          {sourceName} keeps its identity, dependencies and history. The current
          version is archived and can be restored.
        </p>

        {!preflight && !error && (
          <p className="mt-4 text-small text-ink-secondary">
            Staging and validating the file…
          </p>
        )}

        {error && (
          <p className="mt-4 rounded-md bg-red-50 p-3 text-small text-red-700">
            {error}
          </p>
        )}

        {compat && (
          <div className="mt-4 space-y-3 text-[13px]">
            <dl>
              <Row label="Current file" value={compat.currentFileName} />
              <Row label="New file" value={compat.proposedFileName} />
              <Row
                label="Rows"
                value={`${compat.currentRowCount ?? "—"} → ${compat.proposedRowCount ?? "—"}`}
              />
              <Row
                label="Version"
                value={`v${preflight.activeVersion.versionNumber} → v${preflight.version.versionNumber}`}
              />
              <Row label="Update mode" value="Replace with new version" />
            </dl>

            <div>
              <p className="font-medium text-ink-primary">Schema</p>
              <ul className="mt-1 space-y-0.5 text-ink-secondary">
                <li>
                  Added:{" "}
                  {compat.addedColumns.length
                    ? compat.addedColumns.join(", ")
                    : "none"}
                </li>
                <li>
                  Removed:{" "}
                  {compat.removedColumns.length
                    ? compat.removedColumns.join(", ")
                    : "none"}
                </li>
                <li>
                  Type changes:{" "}
                  {compat.typeChangedColumns.length
                    ? compat.typeChangedColumns
                        .map((c) => `${c.column} (${c.from} → ${c.to})`)
                        .join(", ")
                    : "none"}
                </li>
              </ul>
            </div>

            <div>
              <p className="font-medium text-ink-primary">Affected dependencies</p>
              <p className="mt-1 text-ink-secondary">
                {compat.dependencies.length
                  ? compat.dependencies.map((d) => d.name).join(", ")
                  : "No saved queries reference this source."}
              </p>
            </div>

            {compat.warnings.length > 0 && (
              <ul className="space-y-0.5 text-amber-700">
                {compat.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}

            {compat.blockers.length > 0 && (
              <ul className="space-y-0.5 rounded-md bg-red-50 p-3 text-red-700">
                {compat.blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-300 bg-white px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy || !preflight?.canActivate}
            className="rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
          >
            {busy ? "Activating…" : "Activate new version"}
          </button>
        </div>
      </div>
    </div>
  );
}
