"use client";

import { NetworkConnectionsPanel } from "@/app/admin/repositories/network-connections-panel";
import { useConnectedSourceActions } from "./use-connected-source-actions";

export function NetworkFileConnectionsPanel() {
  const { invalidateConnectedSources } = useConnectedSourceActions();

  return (
    <div>
      <NetworkConnectionsPanel onSaved={invalidateConnectedSources} />
    </div>
  );
}
