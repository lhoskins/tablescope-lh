"use client";

import type { DataPlane } from "./types";

type DeleteTenantModalProps = {
  deleteFor: DataPlane;
  deleteAppTenant: boolean;
  setDeleteAppTenant: (value: boolean) => void;
  deleteError: string | null;
  isPending: boolean;
  onDelete: () => void;
  onCancel: () => void;
};

export function DeleteTenantModal({
  deleteFor,
  deleteAppTenant,
  setDeleteAppTenant,
  deleteError,
  isPending,
  onDelete,
  onCancel,
}: DeleteTenantModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-xl">
        <h2 className="text-lg font-medium text-slate-900">
          Delete tenant{" "}
          <span className="font-mono">{deleteFor.tenant_id}</span>?
        </h2>
        <p className="mt-2 text-sm text-slate-600">
          This permanently decommissions the tenant data plane. This action
          cannot be undone.
        </p>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>Undeploys all of the tenant&apos;s VDBs and removes their records.</li>
          <li>Deletes the tenant folder structure and uploaded data.</li>
          <li>
            Removes the isolated Teiid container (
            <span className="font-mono">tenant-{deleteFor.tenant_id}-teiid</span>
            ) and its Docker network.
          </li>
        </ul>

        {deleteFor.org_tenant_id != null && (
          <label className="mt-4 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <input
              type="checkbox"
              checked={deleteAppTenant}
              onChange={(e) => setDeleteAppTenant(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              Also delete the bound application tenant (org #
              {deleteFor.org_tenant_id}) and <strong>all its users</strong>.
              Uncheck to keep the app tenant and only tear down the data plane.
            </span>
          </label>
        )}

        {deleteError && (
          <p className="mt-3 text-sm text-red-600">{deleteError}</p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={isPending}
            onClick={onDelete}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            {isPending ? "Deleting…" : "Yes, delete tenant"}
          </button>
        </div>
      </div>
    </div>
  );
}
