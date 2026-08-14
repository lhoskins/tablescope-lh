"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { IconLoader2, IconPlus, IconServer } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { listNetworkFileConnections, type NetworkFileConnection } from "@/lib/api/network-file-connections";
import { BUILDER_QUERY_OPTIONS } from "@/lib/query-options";
import { NetworkRepositoryModal } from "./network-repository-modal";

export function ConnectedNetworkRepositories({ projectId }: { projectId?: string }) {
  const { data: connections, isLoading } = useQuery({
    ...BUILDER_QUERY_OPTIONS,
    queryKey: ["builder", "network-file-connections"],
    queryFn: listNetworkFileConnections,
  });
  const [active, setActive] = useState<NetworkFileConnection | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-small text-ink-tertiary">
        <IconLoader2 size={15} className="animate-spin" /> Loading network
        repositories…
      </div>
    );
  }

  if (!connections || connections.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-secondary px-4 py-6 text-center text-small text-ink-tertiary">
        No network repositories yet. Create one on the{" "}
        <Link
          href={projectId ? `/projects/${projectId}/settings` : "/admin/repositories"}
          className="font-medium text-brand-700 hover:underline"
        >
          Repositories
        </Link>{" "}
        settings page to use it here.
      </div>
    );
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {connections.map((conn) => (
          <div
            key={conn.id}
            className="flex flex-col rounded-xl border border-line-tertiary bg-bg-primary p-3.5"
          >
            <div className="mb-3 flex items-center gap-2.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-bg-tertiary text-ink-tertiary">
                <IconServer size={20} />
              </span>
              <div className="min-w-0">
                <div className="truncate text-[14px] font-semibold text-ink-primary">
                  {conn.name}
                </div>
                <div className="truncate text-caption text-ink-tertiary font-mono">
                  {conn.label}
                </div>
              </div>
            </div>
            <Button
              variant="brandSoft"
              size="sm"
              className="mt-auto w-full"
              onClick={() => setActive(conn)}
            >
              <IconPlus size={14} />
              Browse
            </Button>
          </div>
        ))}
      </div>
      {active && (
        <NetworkRepositoryModal
          connection={active}
          onClose={() => setActive(null)}
        />
      )}
    </div>
  );
}
