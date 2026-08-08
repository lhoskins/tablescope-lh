"use client";

import type { DataSource } from "@/lib/ui/use-project-data";
import type { PreflightDeleteResponse } from "@/lib/api/data-sources";

export function DeleteSourceDialog({
  open,
  source,
  preflight,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  source: DataSource | null;
  preflight: PreflightDeleteResponse | null;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open || !source) return null;
  const title = `Delete "${source.fileName}"?`;
  const safe = preflight?.safe ?? false;
  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm rounded-lg bg-bg-primary p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-ink-primary">{title}</h3>
        <div className="mt-2 space-y-2 text-sm text-ink-secondary">
          {!preflight ? (
            <p>Checking dependencies…</p>
          ) : (
            <>
              {preflight.blockers.length === 0 ? (
                <p>This data source will be permanently deleted.</p>
              ) : (
                <>
                  <p>This data source cannot be deleted yet:</p>
                  <ul className="list-disc space-y-1 pl-5">
                    {preflight.blockers.map((b) => (
                      <li key={b.category}>{b.message}</li>
                    ))}
                  </ul>
                  {preflight.active_query_dependencies.length > 0 && (
                    <div className="text-ink-tertiary">
                      Active tables that depend on this source:{" "}
                      {preflight.active_query_dependencies.map((d) => d.name).join(", ")}
                    </div>
                  )}
                </>
              )}
            </>
          )}
          {error && <p className="text-danger">{error}</p>}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-line-secondary bg-bg-primary px-4 py-1.5 text-sm font-medium text-ink-primary hover:bg-bg-secondary"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={busy || !safe}
            onClick={onConfirm}
            className="rounded-md bg-danger px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}
