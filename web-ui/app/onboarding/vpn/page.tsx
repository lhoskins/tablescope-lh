"use client";

import { useState } from "react";
import { apiClient } from "@/lib/api-client";

type VpnIntakeResponse = { vpn_status: string; message: string };

export default function VpnOnboardingPage() {
  const [publicEndpoint, setPublicEndpoint] = useState("");
  const [cidrs, setCidrs] = useState("");
  const [vendor, setVendor] = useState("");
  const [ike, setIke] = useState<"ikev1" | "ikev2">("ikev2");
  const [routing, setRouting] = useState<"bgp" | "static">("static");
  const [contact, setContact] = useState("");
  const [maintenance, setMaintenance] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const ranges = cidrs
        .split(/[\s,]+/)
        .map((c) => c.trim())
        .filter(Boolean);
      const res = await apiClient.post<VpnIntakeResponse>("/api/tenant/vpn/intake", {
        public_endpoint: publicEndpoint,
        customer_cidr_ranges: ranges,
        gateway_vendor: vendor || null,
        ike_version: ike,
        routing,
        technical_contact: contact || null,
        maintenance_window: maintenance || null,
      });
      setDone(res.message);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const input =
    "w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-slate-400 focus:outline-none";
  const label = "mb-1 block text-sm font-medium text-slate-700";

  if (done) {
    return (
      <main className="mx-auto max-w-lg px-6 py-16 text-center">
        <h1 className="mb-2 text-2xl font-semibold text-slate-900">VPN details received</h1>
        <p className="text-sm text-slate-600">{done}</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="mb-2 text-2xl font-semibold text-slate-900">VPN onboarding</h1>
      <p className="mb-6 text-sm text-slate-600">
        Provide your network details so we can finalize the site-to-site VPN to your
        on-prem environment.
      </p>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label className={label}>Public VPN endpoint (IP or hostname)</label>
          <input
            className={input}
            value={publicEndpoint}
            onChange={(e) => setPublicEndpoint(e.target.value)}
            required
          />
        </div>
        <div>
          <label className={label}>On-prem CIDR ranges (comma or space separated)</label>
          <input
            className={input}
            value={cidrs}
            onChange={(e) => setCidrs(e.target.value)}
            placeholder="10.0.0.0/16, 192.168.1.0/24"
            required
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={label}>Gateway vendor/device</label>
            <input
              className={input}
              value={vendor}
              onChange={(e) => setVendor(e.target.value)}
              placeholder="Cisco ASA, Fortinet…"
            />
          </div>
          <div>
            <label className={label}>IKE version</label>
            <select
              className={input}
              value={ike}
              onChange={(e) => setIke(e.target.value as "ikev1" | "ikev2")}
            >
              <option value="ikev2">IKEv2</option>
              <option value="ikev1">IKEv1</option>
            </select>
          </div>
        </div>
        <div>
          <label className={label}>Routing</label>
          <select
            className={input}
            value={routing}
            onChange={(e) => setRouting(e.target.value as "bgp" | "static")}
          >
            <option value="static">Static</option>
            <option value="bgp">BGP</option>
          </select>
        </div>
        <div>
          <label className={label}>Technical contact</label>
          <input
            className={input}
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            placeholder="name@company.com"
          />
        </div>
        <div>
          <label className={label}>Preferred maintenance window</label>
          <input
            className={input}
            value={maintenance}
            onChange={(e) => setMaintenance(e.target.value)}
            placeholder="Sat 02:00–04:00 UTC"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? "Submitting…" : "Submit VPN details"}
        </button>
      </form>
    </main>
  );
}
