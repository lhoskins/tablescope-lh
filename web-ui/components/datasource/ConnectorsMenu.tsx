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

const SAAS_APPS: { connector: SaasConnector; label: string }[] = [
  { connector: "hubspot", label: "HubSpot" },
  { connector: "salesforce", label: "Salesforce" },
  { connector: "quickbooks", label: "QuickBooks" },
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
            <p className="px-4 pt-1 pb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              Database
            </p>
            <button className={item} onClick={() => choose({ kind: "database" })}>
              Database Table
            </button>
            <div className="my-1 border-t border-slate-100" />
            <p className="px-4 pt-1 pb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              SaaS Apps
            </p>
            {SAAS_APPS.map((a) => (
              <button
                key={a.connector}
                className={item}
                onClick={() => choose({ kind: "saas", connector: a.connector })}
              >
                {a.label}
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
