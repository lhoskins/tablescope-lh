"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { Switch } from "@/components/ui/switch";
import { useToasts, ToastViewport } from "@/components/ui/toast";

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

export function SecuritySettingsPanel() {
  const queryClient = useQueryClient();
  const { toasts, push, dismiss } = useToasts();
  const [confirm2fa, setConfirm2fa] = useState<boolean | null>(null);

  const twoFaQuery = useQuery<{ enabled: boolean }>({
    queryKey: ["settings", "security", "2fa"],
    queryFn: () =>
      apiClient.get<{ enabled: boolean }>("/api/tenants/current/2fa-enforcement"),
  });

  const toggle2fa = useMutation({
    mutationFn: (enabled: boolean) =>
      apiClient.put<{ enabled: boolean }>("/api/tenants/current/2fa-enforcement", {
        enabled,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings", "security", "2fa"], data);
      queryClient.setQueryData<{ enforce_2fa: boolean } | undefined>(
        ["settings", "tenant"],
        (old) => (old ? { ...old, enforce_2fa: data.enabled } : old),
      );
      push(
        data.enabled
          ? "Two-factor authentication is now required for all members"
          : "Two-factor authentication requirement turned off",
        "success",
      );
    },
    onError: (err: unknown) => {
      push(
        err instanceof Error
          ? err.message
          : "Failed to update two-factor authentication setting",
        "error",
      );
    },
    onSettled: () => setConfirm2fa(null),
  });

  const enforce2fa = twoFaQuery.data?.enabled ?? false;

  return (
    <section className="max-w-3xl">
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-ink-primary">Security</h2>
        <p className="mt-1 text-sm text-ink-tertiary">
          Control tenant-wide authentication requirements.
        </p>
      </header>

      <div className="rounded-lg border border-line-secondary bg-bg-primary p-5 shadow-sm">
        <Switch
          id="tenant-2fa"
          checked={enforce2fa}
          pending={twoFaQuery.isLoading || toggle2fa.isPending}
          label="Require two-factor authentication"
          description="Require all tenant members to verify sign-in with an SMS code. Privileged roles may still require MFA under platform security policy even when this tenant-wide setting is off."
          onLabel="On"
          offLabel="Off"
          onChange={(next) => setConfirm2fa(next)}
        />
      </div>

      <ConfirmDialog
        title={
          confirm2fa === true
            ? "Require two-factor authentication?"
            : "Turn off two-factor authentication?"
        }
        description={
          confirm2fa === true
            ? "All members of this tenant will be required to complete SMS MFA at their next sign-in."
            : "Non-privileged members may no longer be required to use MFA. Admin and privileged-role MFA policy remains in effect."
        }
        confirmText={confirm2fa === true ? "Require 2FA" : "Turn off 2FA"}
        open={confirm2fa !== null}
        onCancel={() => setConfirm2fa(null)}
        onConfirm={() => {
          if (confirm2fa !== null) toggle2fa.mutate(confirm2fa);
        }}
      />

      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </section>
  );
}
