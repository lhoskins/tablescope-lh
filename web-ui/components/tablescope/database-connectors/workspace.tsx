"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { IconLoader2, IconPlus } from "@tabler/icons-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { formatDateTime } from "@/lib/format-datetime";
import {
  deleteDbConnection,
  deleteSaasCredential,
  listCreatedConnections,
  listInstalledConnectors,
  testDbConnection,
  testSaasCredential,
  type CreatedConnection,
  type InstalledConnector,
} from "@/lib/api/connectors";
import { connectorSpec } from "./connector-fields";
import { BrandLogo, connectorChip } from "./brand-logo";
import { ConnectionModal } from "./connection-modal";

const INSTALLED_QK = ["connectors", "installed"];
const CREATED_QK = ["connectors", "created-connections"];

function ConnectorTile({
  connector,
  onCreate,
}: {
  connector: InstalledConnector;
  onCreate: () => void;
}) {
  return (
    <div className="flex flex-col rounded-xl border border-line-tertiary bg-bg-primary p-4">
      <div className="mb-3 flex items-center gap-3">
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${connectorChip(
            connector.key,
          )}`}
        >
          <BrandLogo connector={connector.key} size={22} />
        </span>
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold text-ink-primary">
            {connector.name}
          </div>
          <div className="text-caption text-ink-tertiary">
            {connector.kind === "database"
              ? "Database connector"
              : "SaaS connector"}
          </div>
        </div>
      </div>
      <Badge tone="success" className="mb-3 w-fit capitalize">
        {connector.status}
      </Badge>
      <Button
        variant="secondary"
        size="sm"
        className="mt-auto w-full"
        onClick={onCreate}
      >
        <IconPlus size={14} /> Create connection
      </Button>
    </div>
  );
}

export function DatabaseConnectorsWorkspace() {
  const queryClient = useQueryClient();
  const { data: installed, isLoading: loadingInstalled } = useQuery({
    queryKey: INSTALLED_QK,
    queryFn: listInstalledConnectors,
  });
  const { data: created, isLoading: loadingCreated } = useQuery({
    queryKey: CREATED_QK,
    queryFn: listCreatedConnections,
  });

  const [modalKey, setModalKey] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<CreatedConnection | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testMsg, setTestMsg] = useState<{ id: string; ok: boolean; text: string } | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<CreatedConnection | null>(null);

  const refreshCreated = () =>
    queryClient.invalidateQueries({ queryKey: CREATED_QK });

  const openCreate = (key: string) => {
    setEditTarget(null);
    setModalKey(key);
  };

  const openEdit = (conn: CreatedConnection) => {
    setEditTarget(conn);
    setModalKey(conn.connectorKey);
  };

  const rowId = (c: CreatedConnection) => `${c.kind}-${c.id}`;

  const handleTest = async (conn: CreatedConnection) => {
    const id = rowId(conn);
    setTestingId(id);
    setTestMsg(null);
    try {
      const res =
        conn.kind === "database"
          ? await testDbConnection(conn.id)
          : await testSaasCredential(conn.id);
      setTestMsg({ id, ok: res.success, text: res.message });
      refreshCreated();
    } catch (err) {
      setTestMsg({
        id,
        ok: false,
        text: err instanceof Error ? err.message : "Test failed",
      });
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      if (deleteTarget.kind === "database")
        await deleteDbConnection(deleteTarget.id);
      else await deleteSaasCredential(deleteTarget.id);
      refreshCreated();
    } finally {
      setDeleteTarget(null);
    }
  };

  const activeSpec = modalKey ? connectorSpec(modalKey) : undefined;

  return (
    <div className="space-y-8">
      {/* Installed connectors */}
      <section>
        <h2 className="mb-1 text-h2 text-ink-primary">Installed connectors</h2>
        <p className="mb-4 text-small text-ink-tertiary">
          Create reusable database/SaaS connections with a friendly name. These
          connections are later used by the Data Source Builder.
        </p>
        {loadingInstalled ? (
          <div className="flex items-center gap-2 py-8 text-ink-tertiary">
            <IconLoader2 size={16} className="animate-spin" /> Loading connectors…
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {(installed ?? []).map((c) => (
              <ConnectorTile
                key={c.key}
                connector={c}
                onCreate={() => openCreate(c.key)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Created connections */}
      <section>
        <div className="mb-4 flex items-baseline gap-3">
          <h2 className="text-h2 text-ink-primary">Created connections</h2>
          <span className="text-small text-ink-tertiary">
            Friendly names shown here appear under Connected Databases in the Data
            Source Builder.
          </span>
        </div>

        <div className="overflow-hidden rounded-xl border border-line-tertiary bg-bg-primary">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-line-tertiary bg-bg-tertiary text-left text-caption uppercase tracking-wide text-ink-tertiary">
                <th className="px-4 py-2.5 font-medium">Friendly name</th>
                <th className="px-4 py-2.5 font-medium">Connector</th>
                <th className="px-4 py-2.5 font-medium">Host / Account</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Last tested</th>
                <th className="px-4 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loadingCreated && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink-tertiary">
                    Loading connections…
                  </td>
                </tr>
              )}
              {!loadingCreated && (created ?? []).length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink-tertiary">
                    No connections yet. Pick a connector above to create one.
                  </td>
                </tr>
              )}
              {(created ?? []).map((c) => {
                const id = rowId(c);
                const msg = testMsg?.id === id ? testMsg : null;
                return (
                  <tr
                    key={id}
                    className="border-b border-line-tertiary last:border-0"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <span
                          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${connectorChip(
                            c.connectorKey,
                          )}`}
                        >
                          <BrandLogo connector={c.connectorKey} size={16} />
                        </span>
                        <span className="font-medium text-ink-primary">
                          {c.friendlyName}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-ink-secondary">
                      {c.connectorName}
                    </td>
                    <td className="px-4 py-3 text-ink-secondary">
                      {c.hostOrAccount}
                    </td>
                    <td className="px-4 py-3">
                      {msg ? (
                        <Badge tone={msg.ok ? "success" : "danger"}>
                          {msg.ok ? "Connected" : "Failed"}
                        </Badge>
                      ) : (
                        <Badge tone="success">Connected</Badge>
                      )}
                    </td>
                    <td className="px-4 py-3 text-ink-tertiary">
                      {formatDateTime(c.lastTested) ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openEdit(c)}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleTest(c)}
                          disabled={testingId === id}
                        >
                          {testingId === id && (
                            <IconLoader2 size={13} className="animate-spin" />
                          )}
                          Test
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-danger hover:text-danger"
                          onClick={() => setDeleteTarget(c)}
                        >
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {activeSpec && (
        <ConnectionModal
          spec={activeSpec}
          editTarget={editTarget}
          onClose={() => {
            setModalKey(null);
            setEditTarget(null);
          }}
          onSaved={() => {
            setModalKey(null);
            setEditTarget(null);
            refreshCreated();
          }}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete connection?"
        message={
          deleteTarget
            ? `Remove "${deleteTarget.friendlyName}"? Data sources already created from it are not affected.`
            : ""
        }
        confirmLabel="Delete"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
