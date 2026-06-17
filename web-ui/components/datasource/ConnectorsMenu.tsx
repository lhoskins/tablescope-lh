"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api-client";
import { DatabaseTableWizard, DB_TYPES } from "@/components/datasource/DatabaseTableWizard";
import { SaasSourceWizard } from "@/components/datasource/SaasSourceWizard";

// Single "Connectors" dropdown that replaces the separate "Connect Database
// Table" and "Connect SaaS App" buttons.  It opens the database-table wizard or
// the SaaS wizard (pre-selected to the chosen app) so every external data source
// is created from one entry point.  Previously-saved connections appear under a
// "Connected" category so the user can reuse them without re-authenticating.

type SaasConnector = "hubspot" | "salesforce" | "quickbooks";

type ActiveWizard =
  | null
  | { kind: "database"; dbType: string; connectionId?: number }
  | { kind: "saas"; connector: SaasConnector; credentialId?: number };

type SavedConnection = {
  id: number;
  name: string;
  db_type: string;
};

type SavedCredential = {
  id: number;
  connector_type: string;
  display_name: string;
};

// Flat list of every connector (no group headers). Each database engine is
// listed individually above the SaaS apps; every entry opens its own
// configuration wizard (the DB wizard pre-selected to the chosen engine).
const CONNECTORS: { key: string; label: string; wizard: ActiveWizard }[] = [
  ...DB_TYPES.map((d) => ({
    key: d.value,
    label: d.label,
    wizard: { kind: "database" as const, dbType: d.value },
  })),
  { key: "hubspot", label: "HubSpot", wizard: { kind: "saas", connector: "hubspot" } },
  { key: "salesforce", label: "Salesforce", wizard: { kind: "saas", connector: "salesforce" } },
  { key: "quickbooks", label: "QuickBooks", wizard: { kind: "saas", connector: "quickbooks" } },
];

export function ConnectorsMenu({
  projectId,
  onCreated,
  label = "+ Connectors",
}: {
  projectId?: number;
  onCreated: () => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<ActiveWizard>(null);
  const [savedConnections, setSavedConnections] = useState<SavedConnection[]>([]);
  const [savedCreds, setSavedCreds] = useState<SavedCredential[]>([]);

  // Refresh the "Connected" category whenever the menu opens.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      try {
        const [conns, creds] = await Promise.all([
          apiClient.get<SavedConnection[]>("/api/database-sources/connections"),
          apiClient.get<SavedCredential[]>("/api/saas-sources/credentials"),
        ]);
        if (cancelled) return;
        setSavedConnections(conns);
        setSavedCreds(creds);
      } catch {
        // Non-fatal — the menu still works for creating new connections.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  function choose(w: ActiveWizard) {
    setActive(w);
    setOpen(false);
  }

  const item =
    "block w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50";
  const heading =
    "px-4 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400";

  const hasConnected = savedConnections.length > 0 || savedCreds.length > 0;

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 rounded-md border border-brand bg-brand/5 px-4 py-2 text-sm font-medium text-brand hover:bg-brand/10"
      >
        {label}
        <span className="text-xs">▾</span>
      </button>

      {open && (
        <>
          {/* Click-away backdrop */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
            aria-hidden
          />
          <div className="absolute left-0 z-20 mt-1 max-h-96 w-64 overflow-y-auto rounded-md border border-slate-200 bg-white py-1 shadow-lg">
            {hasConnected && (
              <>
                <div className={heading}>Connected</div>
                {savedConnections.map((c) => (
                  <button
                    key={`conn-${c.id}`}
                    className={item}
                    onClick={() =>
                      choose({ kind: "database", dbType: c.db_type, connectionId: c.id })
                    }
                  >
                    {c.name}
                    <span className="ml-1 text-xs text-slate-400">({c.db_type})</span>
                  </button>
                ))}
                {savedCreds.map((c) => (
                  <button
                    key={`cred-${c.id}`}
                    className={item}
                    onClick={() =>
                      choose({
                        kind: "saas",
                        connector: c.connector_type as SaasConnector,
                        credentialId: c.id,
                      })
                    }
                  >
                    {c.display_name}
                    <span className="ml-1 text-xs text-slate-400">
                      ({c.connector_type})
                    </span>
                  </button>
                ))}
                <div className="my-1 border-t border-slate-100" />
                <div className={heading}>New connection</div>
              </>
            )}
            {CONNECTORS.map((c) => (
              <button key={c.key} className={item} onClick={() => choose(c.wizard)}>
                {c.label}
              </button>
            ))}
          </div>
        </>
      )}

      {active?.kind === "database" && (
        <DatabaseTableWizard
          projectId={projectId}
          initialDbType={active.dbType}
          initialConnectionId={active.connectionId}
          onClose={() => setActive(null)}
          onCreated={onCreated}
        />
      )}

      {active?.kind === "saas" && (
        <SaasSourceWizard
          projectId={projectId}
          initialConnector={active.connector}
          initialCredentialId={active.credentialId}
          onClose={() => setActive(null)}
          onCreated={onCreated}
        />
      )}
    </div>
  );
}
