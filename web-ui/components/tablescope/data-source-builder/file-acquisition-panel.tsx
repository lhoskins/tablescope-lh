"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  IconCloudUpload,
  IconLink,
  IconServer,
  IconShield,
} from "@tabler/icons-react";
import { cn } from "@/lib/cn";
import { useCurrentUser } from "@/lib/ui/use-shell-data";
import { getImportCapabilities } from "@/lib/api/data-source-builder";
import { AiUploadDropzone } from "./ai-upload-dropzone";
import { NetworkImportForm } from "./network-import-form";
import { NetworkSecurityPanel } from "./network-security-panel";
import { UrlImportForm } from "./url-import-form";

type Method = "local" | "url" | "network" | "security";

export function FileAcquisitionPanel({
  onUploadsDone,
}: {
  onUploadsDone?: () => void;
}) {
  const { data: identity } = useCurrentUser();
  const isAdmin =
    identity?.user.isSuperAdmin ||
    ["admin", "tenant_admin", "root_admin"].includes(
      identity?.user.rawRole ?? "",
    );

  const [method, setMethod] = useState<Method>("local");
  const { data: capabilities } = useQuery({
    queryKey: ["builder", "import-capabilities"],
    queryFn: getImportCapabilities,
    staleTime: 5 * 60 * 1000,
  });

  const METHODS = useMemo(
    () =>
      [
        {
          key: "local" as const,
          label: "Upload file",
          hint: "From this computer",
          icon: IconCloudUpload,
        },
        {
          key: "url" as const,
          label: "File URL",
          hint: "Secure https link",
          icon: IconLink,
        },
        {
          key: "network" as const,
          label: "Network path",
          hint: "Approved location",
          icon: IconServer,
        },
        ...(isAdmin
          ? [
              {
                key: "security" as const,
                label: "Security",
                hint: "Allowed SMB hosts",
                icon: IconShield,
              },
            ]
          : []),
      ] as { key: Method; label: string; hint: string; icon: typeof IconCloudUpload }[],
    [isAdmin],
  );

  const enabled: Record<Method, boolean> = {
    local: true,
    url: capabilities?.url_import_enabled ?? false,
    network: capabilities?.network_import_enabled ?? false,
    security: true,
  };

  return (
    <section className="rounded-xl border border-line-tertiary p-4">
      <h3 className="text-h3 text-ink-primary">
        {method === "security" ? "Security" : "Add files"}
      </h3>
      <p className="mt-0.5 text-small text-ink-tertiary">
        {method === "security"
          ? "Manage the SMB hosts that are approved for network file imports."
          : "Upload from this computer, import from a secure file URL, or pull from an approved network location."}
      </p>

      <div
        role="tablist"
        aria-label="File acquisition method"
        className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-4"
      >
        {METHODS.map((m) => {
          const Icon = m.icon;
          const active = method === m.key;
          const isEnabled = enabled[m.key];
          return (
            <button
              key={m.key}
              role="tab"
              type="button"
              aria-selected={active}
              disabled={!isEnabled}
              onClick={() => setMethod(m.key as Method)}
              className={cn(
                "flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors",
                active
                  ? "border-brand-500 bg-brand-50/50"
                  : "border-line-tertiary hover:bg-bg-secondary/50",
                !isEnabled &&
                  "cursor-not-allowed opacity-50 hover:bg-transparent",
              )}
            >
              <span
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                  active
                    ? "bg-brand-100 text-brand-600"
                    : "bg-bg-tertiary text-ink-tertiary",
                )}
              >
                <Icon size={17} />
              </span>
              <span className="min-w-0">
                <span
                  className={cn(
                    "block truncate text-[13px] font-semibold",
                    active ? "text-brand-700" : "text-ink-primary",
                  )}
                >
                  {m.label}
                </span>
                <span className="block truncate text-caption text-ink-tertiary">
                  {isEnabled ? m.hint : "Not enabled"}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-4">
        {method === "local" && (
          <AiUploadDropzone onUploadsDone={onUploadsDone} />
        )}
        {method === "url" && <UrlImportForm onImported={onUploadsDone} />}
        {method === "network" && (
          <NetworkImportForm
            connections={capabilities?.network_connections ?? []}
            hosts={capabilities?.network_hosts ?? []}
            onImported={onUploadsDone}
          />
        )}
        {method === "security" && <NetworkSecurityPanel />}
      </div>
    </section>
  );
}
