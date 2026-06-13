"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiClient } from "@/lib/api-client";

type CheckoutResponse = {
  checkout_url: string;
  provisioning_request_id: number;
};

function CheckoutForm() {
  const params = useSearchParams();
  const tierKey = params.get("tier") || "basic_cloud";

  const [companyName, setCompanyName] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [tenantSlug, setTenantSlug] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [billingEmail, setBillingEmail] = useState("");
  const [region, setRegion] = useState("us-west-2");
  const [interval, setInterval] = useState<"month" | "year">("month");
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!agreed) {
      setError("Please accept the terms to continue.");
      return;
    }
    setLoading(true);
    try {
      const res = await apiClient.post<CheckoutResponse>(
        "/api/billing/checkout/session",
        {
          tier_key: tierKey,
          company_name: companyName,
          tenant_name: tenantName,
          tenant_slug: tenantSlug,
          tenant_admin_first_name: firstName || null,
          tenant_admin_last_name: lastName || null,
          tenant_admin_email: adminEmail,
          billing_email: billingEmail || null,
          region,
          billing_interval: interval,
          agreed_to_terms: agreed,
        },
      );
      window.location.href = res.checkout_url;
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const input =
    "w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-slate-400 focus:outline-none";
  const label = "mb-1 block text-sm font-medium text-slate-700";

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="mb-2 text-2xl font-semibold text-slate-900">
        Set up your workspace
      </h1>
      <p className="mb-6 text-sm text-slate-600">
        Plan: <strong>{tierKey.replace(/_/g, " ")}</strong>
      </p>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label className={label}>Company name</label>
          <input
            className={input}
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            required
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={label}>Workspace name</label>
            <input
              className={input}
              value={tenantName}
              onChange={(e) => setTenantName(e.target.value)}
              required
            />
          </div>
          <div>
            <label className={label}>Workspace slug</label>
            <input
              className={input}
              value={tenantSlug}
              onChange={(e) => setTenantSlug(e.target.value)}
              placeholder="acme-co"
              required
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={label}>Admin first name</label>
            <input
              className={input}
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
            />
          </div>
          <div>
            <label className={label}>Admin last name</label>
            <input
              className={input}
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label className={label}>Admin email</label>
          <input
            type="email"
            className={input}
            value={adminEmail}
            onChange={(e) => setAdminEmail(e.target.value)}
            required
          />
        </div>
        <div>
          <label className={label}>Billing email (optional)</label>
          <input
            type="email"
            className={input}
            value={billingEmail}
            onChange={(e) => setBillingEmail(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={label}>Region</label>
            <input
              className={input}
              value={region}
              onChange={(e) => setRegion(e.target.value)}
            />
          </div>
          <div>
            <label className={label}>Billing interval</label>
            <select
              className={input}
              value={interval}
              onChange={(e) => setInterval(e.target.value as "month" | "year")}
            >
              <option value="month">Monthly</option>
              <option value="year">Annual</option>
            </select>
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
          />
          I agree to the Terms of Service and Privacy Policy.
        </label>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? "Redirecting to checkout…" : "Continue to payment"}
        </button>
      </form>
    </main>
  );
}

export default function CheckoutPage() {
  return (
    <Suspense fallback={<p className="p-12 text-center text-slate-500">Loading…</p>}>
      <CheckoutForm />
    </Suspense>
  );
}
