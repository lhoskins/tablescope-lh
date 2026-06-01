"use client";

import { useState } from "react";
import { DatabaseTableWizard } from "@/components/datasource/DatabaseTableWizard";
import { SaasSourceWizard } from "@/components/datasource/SaasSourceWizard";

// Single "Connectors" dropdown that replaces the separate "Connect Database
// Table" and "Connect SaaS App" buttons.  It opens the database-table wizard or
// the SaaS wizard (pre-selected to the chosen app) so every external data source
// is created from one entry point.

type SaasConnector = "hubspot" | "salesforce" | "quickbooks";

type ActiveWizard = null | { kind: "database" } | { kind: "saas"; connector: SaasConnector };

// Flat list of every connector (no group headers). Order is database first,
// then the SaaS apps; each entry opens its own configuration wizard.
const CONNECTORS: { key: string; label: string; wizard: ActiveWizard }[] = [
  { key: "database", label: "Database Table", wizard: { kind: "database" } },
  { key: "hubspot", label: "HubSpot", wizard: { kind: "saas", connector: "hubspot" } },
  { key: "salesforce", label: "Salesforce", wizard: { kind: "saas", connector: "salesforce" } },
  { key: "quickbooks", label: "QuickBooks", wizard: { kind: "saas", connector: "quickbooks" } },
];

export function ConnectorsMenu({
  projectId,
  onCreated,
}: {
  projectId?: number;
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<ActiveWizard>(null);

  function choose(w: ActiveWizard) {
    setActive(w);
    setOpen(false);
  }

  const item =
    "block w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50";

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 rounded-md border border-brand bg-brand/5 px-4 py-2 text-sm font-medium text-brand hover:bg-brand/10"
      >
        + Connectors
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
          <div className="absolute left-0 z-20 mt-1 w-56 rounded-md border border-slate-200 bg-white py-1 shadow-lg">
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
          onClose={() => setActive(null)}
          onCreated={onCreated}
        />
      )}

      {active?.kind === "saas" && (
        <SaasSourceWizard
          projectId={projectId}
          initialConnector={active.connector}
          onClose={() => setActive(null)}
          onCreated={onCreated}
        />
      )}
    </div>
  );
}
