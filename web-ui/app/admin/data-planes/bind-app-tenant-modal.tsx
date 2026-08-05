"use client";

import type { AppTenant } from "./types";

type BindAppTenantModalProps = {
  bindFor: string;
  bindCreateNew: boolean;
  setBindCreateNew: (value: boolean) => void;
  bindSlug: string;
  setBindSlug: (value: string) => void;
  bindName: string;
  setBindName: (value: string) => void;
  bindEmail: string;
  setBindEmail: (value: string) => void;
  bindPassword: string;
  setBindPassword: (value: string) => void;
  bindOrgId: number | null;
  setBindOrgId: (value: number | null) => void;
  bindError: string | null;
  appTenants: AppTenant[] | undefined;
  isPending: boolean;
  onSubmit: (e: React.FormEvent) => void;
  onCancel: () => void;
};

export function BindAppTenantModal({
  bindFor,
  bindCreateNew,
  setBindCreateNew,
  bindSlug,
  setBindSlug,
  bindName,
  setBindName,
  bindEmail,
  setBindEmail,
  bindPassword,
  setBindPassword,
  bindOrgId,
  setBindOrgId,
  bindError,
  appTenants,
  isPending,
  onSubmit,
  onCancel,
}: BindAppTenantModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-xl"
      >
        <h2 className="text-lg font-medium text-slate-900">
          Bind app tenant to{" "}
          <span className="font-mono">{bindFor}</span>
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Link this data plane to an application tenant so logins for that
          tenant route to its dedicated Teiid container.
        </p>

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => setBindCreateNew(true)}
            className={`flex-1 rounded-lg border p-3 text-left text-sm ${
              bindCreateNew
                ? "border-brand bg-brand/5 ring-1 ring-brand"
                : "border-slate-200 hover:border-slate-300"
            }`}
          >
            <span className="block font-semibold text-slate-900">
              Create new app tenant
            </span>
            <span className="text-xs text-slate-500">Slug + root admin login</span>
          </button>
          <button
            type="button"
            onClick={() => setBindCreateNew(false)}
            className={`flex-1 rounded-lg border p-3 text-left text-sm ${
              !bindCreateNew
                ? "border-brand bg-brand/5 ring-1 ring-brand"
                : "border-slate-200 hover:border-slate-300"
            }`}
          >
            <span className="block font-semibold text-slate-900">
              Link existing tenant
            </span>
            <span className="text-xs text-slate-500">Pick an existing org tenant</span>
          </button>
        </div>

        {bindCreateNew ? (
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Slug <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={bindSlug}
                onChange={(e) =>
                  setBindSlug(
                    e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")
                  )
                }
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="acme"
              />
              <p className="mt-1 text-xs text-slate-400">
                Login URL: /{bindSlug || "slug"}/login
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Display name
              </label>
              <input
                type="text"
                value={bindName}
                onChange={(e) => setBindName(e.target.value)}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="Acme Corporation"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Admin email <span className="text-red-500">*</span>
              </label>
              <input
                type="email"
                value={bindEmail}
                onChange={(e) => setBindEmail(e.target.value)}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="admin@acme.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Admin password <span className="text-red-500">*</span>
              </label>
              <input
                type="password"
                value={bindPassword}
                onChange={(e) => setBindPassword(e.target.value)}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
                placeholder="••••••••"
              />
            </div>
          </div>
        ) : (
          <div className="mt-4">
            <label className="block text-sm font-medium text-slate-700">
              Existing app tenant
            </label>
            <select
              value={bindOrgId ?? ""}
              onChange={(e) =>
                setBindOrgId(e.target.value ? Number(e.target.value) : null)
              }
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            >
              <option value="">Select a tenant…</option>
              {appTenants?.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.slug} — {t.name} (#{t.id})
                </option>
              ))}
            </select>
          </div>
        )}

        {bindError && (
          <p className="mt-3 text-sm text-red-600">{bindError}</p>
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
            type="submit"
            disabled={isPending}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90 disabled:opacity-50"
          >
            {isPending ? "Binding…" : "Bind"}
          </button>
        </div>
      </form>
    </div>
  );
}
