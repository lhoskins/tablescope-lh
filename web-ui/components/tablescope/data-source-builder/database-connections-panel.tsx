"use client";

import { DatabaseConnectorsWorkspace } from "@/components/tablescope/database-connectors/workspace";
import type { CreatedConnection } from "@/lib/api/connectors";
import { TableSelectModal } from "./table-select-modal";
import { SaaSSourceModal } from "./saas-source-modal";
import { GoogleSheetsSourceModal } from "./google-sheets-source-modal";
import { useConnectedSourceActions } from "./use-connected-source-actions";

export function DatabaseConnectionsPanel({ projectId }: { projectId?: string }) {
  const {
    activeDbSourceId,
    activeSaasCredential,
    activeGoogleSheetsCredential,
    openDbFromCreatedConnection,
    openSaasFromCreatedConnection,
    closeDbModal,
    closeSaasModal,
    closeGoogleSheetsModal,
    invalidateConnectedSources,
  } = useConnectedSourceActions();

  const handleUseInBuilder = (conn: CreatedConnection) => {
    if (conn.kind === "database") {
      openDbFromCreatedConnection(conn);
    } else {
      openSaasFromCreatedConnection(conn);
    }
  };

  return (
    <div>
      <DatabaseConnectorsWorkspace
        projectId={projectId}
        onUseInBuilder={handleUseInBuilder}
        onConnectionSaved={invalidateConnectedSources}
      />
      {activeDbSourceId && (
        <TableSelectModal sourceId={activeDbSourceId} onClose={closeDbModal} />
      )}
      {activeSaasCredential && (
        <SaaSSourceModal credential={activeSaasCredential} onClose={closeSaasModal} />
      )}
      {activeGoogleSheetsCredential && (
        <GoogleSheetsSourceModal
          credential={activeGoogleSheetsCredential}
          onClose={closeGoogleSheetsModal}
        />
      )}
    </div>
  );
}
