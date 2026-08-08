"use client";

import { NetworkHostsPanel } from "./network-hosts-panel";

export default function AllowedHostsPage() {
  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Allowed Hosts</h1>
        <p className="mt-1 text-sm text-slate-500">
          Friendly names for SMB hosts that are approved for network file imports.
        </p>
      </div>
      <NetworkHostsPanel />
    </section>
  );
}
