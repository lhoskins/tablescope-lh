"use client";

import type { DeleteResult } from "./types";

type TeardownModalProps = {
  teardown: DeleteResult;
  onDone: () => void;
};

export function TeardownModal({ teardown, onDone }: TeardownModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl rounded-lg border border-slate-200 bg-white p-6 shadow-xl">
        <h2 className="text-lg font-medium text-slate-900">
          Tenant <span className="font-mono">{teardown.tenant_id}</span>{" "}
          removed
        </h2>
        <p className="mt-2 text-sm text-slate-600">{teardown.note}</p>
        {Object.keys(teardown.deleted_rows).length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            Deleted:{" "}
            {Object.entries(teardown.deleted_rows)
              .filter(([, n]) => n > 0)
              .map(([t, n]) => `${n} ${t}`)
              .join(", ") || "no application rows"}
            .
          </p>
        )}
        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-sm font-medium text-slate-700">
              Host teardown script
            </span>
            <button
              type="button"
              onClick={() =>
                navigator.clipboard?.writeText(teardown.teardown_script)
              }
              className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
            >
              Copy
            </button>
          </div>
          <pre className="max-h-72 overflow-auto rounded-md bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">
            {teardown.teardown_script}
          </pre>
          <p className="mt-2 text-xs text-slate-500">
            Run this on the EC2 host to remove the isolated container, network
            and on-host VDB directory (root/Docker operations the control plane
            does not perform itself).
          </p>
        </div>
        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onDone}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
