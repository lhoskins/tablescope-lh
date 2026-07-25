"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import Link from "next/link";
import { useToasts, ToastViewport } from "@/components/ui/toast";

type TenantSettings = {
  id: number;
  name: string;
  slug: string;
  is_active: boolean;
  enforce_2fa: boolean;
  allowed_domains_enabled: boolean;
  logo_url: string | null;
  login_url: string | null;
  created_at: string;
  updated_at: string;
};

type ReprocessResponse = {
  tenant_id: number;
  status: string;
  total_projects: number;
  projects_queued: number;
  projects_skipped: number;
  job_ids: string[];
  force: boolean;
};

function ConfirmDialog({
  title,
  description,
  confirmText,
  onConfirm,
  onCancel,
  open,
}: {
  title: string;
  description: React.ReactNode;
  confirmText: string;
  onConfirm: () => void;
  onCancel: () => void;
  open: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-lg border border-line-tertiary bg-bg-primary p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-ink-primary">{title}</h3>
        <div className="mt-2 text-sm text-ink-secondary">{description}</div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-line-secondary px-4 py-2 text-sm font-medium text-ink-primary hover:bg-bg-secondary"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg hover:bg-brand/90"
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}

export function TenantSettingsPanel() {
  const { toasts, push, dismiss } = useToasts();
  const [confirmReprocess, setConfirmReprocess] = useState(false);
  const [forceReprocess, setForceReprocess] = useState(false);

  const settingsQuery = useQuery<TenantSettings>({
    queryKey: ["settings", "tenant"],
    queryFn: () => apiClient.get<TenantSettings>("/api/tenants/current/settings"),
  });

  const twoFaQuery = useQuery<{ enabled: boolean }>({
    queryKey: ["settings", "security", "2fa"],
    queryFn: () =>
      apiClient.get<{ enabled: boolean }>("/api/tenants/current/2fa-enforcement"),
    enabled: !!settingsQuery.data,
  });

  const reprocess = useMutation({
    mutationFn: () =>
      apiClient.post<ReprocessResponse>(
        `/api/tenants/current/reprocess-documents?force=${forceReprocess ? "true" : "false"}`,
        {},
      ),
    onSuccess: (data) => {
      setConfirmReprocess(false);
      push(
        `Queued ${data.projects_queued} project reprocess(s)${data.projects_skipped > 0 ? `, ${data.projects_skipped} already running` : ""}`,
        "success",
      );
    },
    onError: (err: unknown) => {
      setConfirmReprocess(false);
      push(
        err instanceof Error ? err.message : "Failed to queue tenant reprocess",
        "error",
      );
    },
  });

  const enforce2fa = twoFaQuery.data?.enabled ?? false;

  return (
    <section className="max-w-3xl">
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-ink-primary">My Tenant</h2>
        <p className="mt-1 text-sm text-ink-tertiary">
          Organization details and tenant-wide maintenance.
        </p>
      </header>

      {settingsQuery.isLoading && (
        <div className="space-y-3">
          <div className="h-24 animate-pulse rounded-lg bg-bg-tertiary" />
          <div className="h-32 animate-pulse rounded-lg bg-bg-tertiary" />
        </div>
      )}
      {settingsQuery.error && (
        <p className="text-sm text-danger">
          {(settingsQuery.error as Error).message}
        </p>
      )}

      {settingsQuery.data && (
        <div className="space-y-6">
          <div className="rounded-lg border border-line-secondary bg-bg-primary p-5 shadow-sm">
            <h3 className="mb-4 text-sm font-semibold text-ink-primary">
              Organization profile
            </h3>
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">
                  Organization name
                </dt>
                <dd className="mt-0.5 text-sm text-ink-primary">
                  {settingsQuery.data.name}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">
                  Slug
                </dt>
                <dd className="mt-0.5 text-sm font-mono text-ink-primary">
                  {settingsQuery.data.slug}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">
                  Status
                </dt>
                <dd className="mt-0.5">
                  {settingsQuery.data.is_active ? (
                    <span className="inline-flex rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                      Active
                    </span>
                  ) : (
                    <span className="inline-flex rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">
                      Inactive
                    </span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">
                  Login URL
                </dt>
                <dd className="mt-0.5 text-sm text-ink-primary">
                  {settingsQuery.data.login_url ? (
                    <a
                      href={settingsQuery.data.login_url}
                      className="text-brand hover:underline"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {settingsQuery.data.login_url}
                    </a>
                  ) : (
                    "—"
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-tertiary">
                  Created
                </dt>
                <dd className="mt-0.5 text-sm text-ink-primary">
                  {new Date(settingsQuery.data.created_at).toLocaleDateString()}
                </dd>
              </div>
            </dl>
          </div>

          <div className="rounded-lg border border-line-secondary bg-bg-primary p-5 shadow-sm">
            <h3 className="mb-4 text-sm font-semibold text-ink-primary">
              Tenant maintenance
            </h3>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-sm text-ink-primary">Reprocess documents</p>
                <p className="text-xs text-ink-tertiary">
                  Rebuild knowledge graphs across every project in this tenant.
                  This may take a while.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1.5 text-xs text-ink-secondary">
                  <input
                    type="checkbox"
                    checked={forceReprocess}
                    onChange={(e) => setForceReprocess(e.target.checked)}
                    className="h-3.5 w-3.5 rounded border-line-secondary text-brand focus:ring-brand"
                  />
                  Force unchanged files
                </label>
                <button
                  type="button"
                  onClick={() => setConfirmReprocess(true)}
                  disabled={reprocess.isPending}
                  className="rounded-md bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50"
                >
                  {reprocess.isPending ? "Queueing…" : "Reprocess all"}
                </button>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-line-secondary bg-bg-primary p-5 shadow-sm">
            <h3 className="mb-2 text-sm font-semibold text-ink-primary">
              Security
            </h3>
            <p className="text-sm text-ink-secondary">
              Two-factor authentication is{" "}
              <strong>{enforce2fa ? "required" : "off"}</strong> for this tenant.
            </p>
            <Link
              href="/admin/settings/security"
              className="mt-2 inline-block text-sm text-brand hover:underline"
            >
              Manage security settings →
            </Link>
          </div>
        </div>
      )}

      <ConfirmDialog
        title="Reprocess all tenant documents?"
        description={
          <>
            This enqueues a knowledge-graph rebuild for every project in this
            tenant.
            {forceReprocess && (
              <>
                {" "}
                <strong>Force</strong> is enabled, so unchanged files will also
                be reprocessed.
              </>
            )}
          </>
        }
        confirmText="Queue reprocess"
        open={confirmReprocess}
        onCancel={() => setConfirmReprocess(false)}
        onConfirm={() => reprocess.mutate()}
      />

      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </section>
  );
}
