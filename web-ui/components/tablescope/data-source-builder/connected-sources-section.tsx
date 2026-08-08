"use client";

import { useQuery } from "@tanstack/react-query";
import { IconLoader2, IconPlus, IconServer } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { listConnectedSources, type ConnectedSource } from "@/lib/api/data-source-catalog";
import { connectorDisplayName } from "@/lib/api/connectors";
import { useBuilderStore, type SessionSource } from "@/lib/stores/data-source-builder-store";
import { BrandLogo, connectorChip } from "../database-connectors/brand-logo";
import { TableSelectModal } from "./table-select-modal";
import { SaaSSourceModal } from "./saas-source-modal";
import { NetworkRepositoryModal } from "./network-repository-modal";
import { useConnectedSourceActions } from "./use-connected-source-actions";

function isSourceAdded(sources: SessionSource[], src: ConnectedSource): boolean {
  if (src.kind === "database" && src.connectionId) {
    return sources.some(
      (s) => s.connectionConfig.connection_id === String(src.connectionId),
    );
  }
  if (src.kind === "saas" && src.credentialId) {
    return sources.some(
      (s) =>
        s.isSaaS &&
        s.connectionConfig.credential_id === String(src.credentialId),
    );
  }
  return false;
}

function ConnectedSourceCard({
  source,
  busy,
  onAction,
}: {
  source: ConnectedSource;
  busy: boolean;
  onAction: (src: ConnectedSource) => void;
}) {
  const sources = useBuilderStore((s) => s.sources);
  const added = isSourceAdded(sources, source);

  const isNetwork = source.kind === "network_repository";
  const actionKey = isNetwork ? "browse" : "create_data_source";
  const hasTarget = isNetwork
    ? !!source.connectionId
    : source.kind === "database"
      ? !!source.connectionId
      : !!source.credentialId;
  const canUse =
    source.enabled && source.allowedActions.includes(actionKey) && hasTarget;
  const label = isNetwork
    ? "Browse"
    : added
      ? "Edit selection"
      : canUse
        ? "Create Data Source"
        : "Shared source";

  return (
    <div className="flex flex-col rounded-xl border border-line-tertiary bg-bg-primary p-3.5">
      <div className="mb-2 flex items-center gap-2.5">
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
            isNetwork ? "bg-bg-tertiary text-ink-tertiary" : connectorChip(source.connectorType),
          )}
        >
          {isNetwork ? (
            <IconServer size={20} />
          ) : (
            <BrandLogo connector={source.connectorType} size={20} />
          )}
        </span>
        <div className="min-w-0">
          <div className="truncate text-[14px] font-semibold text-ink-primary">
            {source.friendlyName}
          </div>
          <div className="truncate text-caption text-ink-tertiary">
            {isNetwork
              ? "Network repository"
              : connectorDisplayName(source.connectorType)}
          </div>
          <div className="truncate text-caption text-ink-tertiary">
            {source.displayLocation}
          </div>
        </div>
      </div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[11px] font-medium",
            source.enabled && (source.status === "connected" || source.status === "ok")
              ? "bg-success/10 text-success"
              : "bg-bg-secondary text-ink-tertiary",
          )}
        >
          {source.enabled ? source.status : "Disabled"}
        </span>
        {source.assignedBy && (
          <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-700">
            Assigned by {source.assignedBy}
          </span>
        )}
      </div>
      <Button
        variant={added ? "secondary" : "brandSoft"}
        size="sm"
        className="mt-auto w-full"
        onClick={() => onAction(source)}
        disabled={busy || !canUse}
      >
        {busy ? (
          <IconLoader2 size={14} className="animate-spin" />
        ) : (
          <IconPlus size={14} />
        )}
        {label}
      </Button>
    </div>
  );
}

export function ConnectedSourcesSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["connected-sources"],
    queryFn: listConnectedSources,
  });

  const {
    busyId,
    error,
    activeDbSourceId,
    activeSaasCredential,
    activeNetworkConnection,
    openDbFromConnectedSource,
    openSaasFromConnectedSource,
    openNetworkFromConnectedSource,
    closeDbModal,
    closeSaasModal,
    closeNetworkModal,
  } = useConnectedSourceActions();

  const handleAction = (src: ConnectedSource) => {
    if (src.kind === "database") {
      openDbFromConnectedSource(src);
    } else if (src.kind === "saas") {
      openSaasFromConnectedSource(src);
    } else if (src.kind === "network_repository") {
      openNetworkFromConnectedSource(src);
    }
  };

  return (
    <section className="space-y-3">
      <h2 className="text-caption font-semibold uppercase tracking-wide text-ink-tertiary">
        Connected Sources
      </h2>

      {isLoading && (
        <div className="flex items-center gap-2 text-small text-ink-tertiary">
          <IconLoader2 size={15} className="animate-spin" /> Loading connected sources…
        </div>
      )}

      {!isLoading && (data ?? []).length === 0 && (
        <div className="rounded-lg border border-dashed border-line-secondary px-4 py-6 text-center text-small text-ink-tertiary">
          No connected sources yet. Create a database, SaaS, or network connection above.
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {(data ?? []).map((src) => (
          <ConnectedSourceCard
            key={src.id}
            source={src}
            busy={busyId === `db-${src.connectionId}`}
            onAction={handleAction}
          />
        ))}
      </div>

      {error && <p className="text-caption text-danger">{error}</p>}

      {activeDbSourceId && (
        <TableSelectModal sourceId={activeDbSourceId} onClose={closeDbModal} />
      )}
      {activeSaasCredential && (
        <SaaSSourceModal credential={activeSaasCredential} onClose={closeSaasModal} />
      )}
      {activeNetworkConnection && (
        <NetworkRepositoryModal
          connection={activeNetworkConnection}
          onClose={closeNetworkModal}
        />
      )}
    </section>
  );
}
