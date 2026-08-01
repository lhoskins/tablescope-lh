"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { IconLoader2, IconPlus } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { listSaasCredentials, type SaasCredential } from "@/lib/api/connectors";
import { useBuilderStore } from "@/lib/stores/data-source-builder-store";
import { BrandLogo, connectorChip } from "../database-connectors/brand-logo";
import { SaaSSourceModal } from "./saas-source-modal";

export function ConnectedSaaS() {
  const { data: credentials, isLoading } = useQuery({
    queryKey: ["builder", "saas-credentials"],
    queryFn: listSaasCredentials,
  });
  const sources = useBuilderStore((s) => s.sources);
  const [active, setActive] = useState<SaasCredential | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-small text-ink-tertiary">
        <IconLoader2 size={15} className="animate-spin" /> Loading SaaS
        connections…
      </div>
    );
  }

  if (!credentials || credentials.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-secondary px-4 py-6 text-center text-small text-ink-tertiary">
        No SaaS connectors yet. Create one on the{" "}
        <Link
          href="/database-connectors"
          className="font-medium text-brand-700 hover:underline"
        >
          Database Connectors
        </Link>{" "}
        page to use it here.
      </div>
    );
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {credentials.map((cred) => {
          const already = sources.find(
            (s) =>
              s.isSaaS &&
              s.connectionConfig.credential_id === String(cred.id),
          );
          return (
            <div
              key={cred.id}
              className="flex flex-col rounded-xl border border-line-tertiary bg-bg-primary p-3.5"
            >
              <div className="mb-3 flex items-center gap-2.5">
                <span
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${connectorChip(
                    cred.connector_type,
                  )}`}
                >
                  <BrandLogo connector={cred.connector_type} size={20} />
                </span>
                <div className="min-w-0">
                  <div className="truncate text-[14px] font-semibold text-ink-primary">
                    {cred.display_name}
                  </div>
                  <div className="truncate text-caption text-ink-tertiary">
                    {cred.connector_type.charAt(0).toUpperCase() +
                      cred.connector_type.slice(1)}
                  </div>
                </div>
              </div>
              <Button
                variant={already ? "secondary" : "brandSoft"}
                size="sm"
                className="mt-auto w-full"
                onClick={() => setActive(cred)}
              >
                <IconPlus size={14} />
                {already ? "Add another object" : "Create Data Source"}
              </Button>
            </div>
          );
        })}
      </div>
      {active && (
        <SaaSSourceModal
          credential={active}
          onClose={() => setActive(null)}
        />
      )}
    </div>
  );
}
