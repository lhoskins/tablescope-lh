"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiClient } from "@/lib/api-client";

type TierCard = {
  tier_key: string;
  display_name: string;
  description: string | null;
  deployment_mode: string;
  requires_data_plane: boolean;
  requires_vpn: boolean;
  monthly_price_cents: number | null;
  annual_price_cents: number | null;
  features: string[];
  has_monthly_price: boolean;
  has_annual_price: boolean;
};

function formatPrice(cents: number | null): string {
  if (cents == null) return "Contact us";
  return `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export default function PricingPage() {
  const [tiers, setTiers] = useState<TierCard[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get<TierCard[]>("/api/billing/catalog")
      .then(setTiers)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="mx-auto max-w-6xl px-6 py-16">
      <div className="mb-12 text-center">
        <h1 className="text-3xl font-semibold text-slate-900">Choose your plan</h1>
        <p className="mt-2 text-slate-600">
          Pick the deployment that fits your data isolation needs.
        </p>
      </div>

      {loading && <p className="text-center text-slate-500">Loading plans…</p>}
      {error && (
        <p className="mx-auto max-w-md rounded-md bg-red-50 px-4 py-3 text-center text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="grid gap-6 md:grid-cols-3">
        {tiers.map((tier) => (
          <div
            key={tier.tier_key}
            className="flex flex-col rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
          >
            <h2 className="text-xl font-semibold text-slate-900">
              {tier.display_name}
            </h2>
            {tier.description && (
              <p className="mt-1 text-sm text-slate-600">{tier.description}</p>
            )}
            <div className="mt-4">
              <span className="text-3xl font-bold text-slate-900">
                {formatPrice(tier.monthly_price_cents)}
              </span>
              {tier.monthly_price_cents != null && (
                <span className="text-sm text-slate-500"> /mo</span>
              )}
            </div>

            <ul className="mt-6 flex-1 space-y-2 text-sm text-slate-700">
              {tier.features.map((f) => (
                <li key={f} className="flex items-start gap-2">
                  <span className="mt-0.5 text-emerald-600">✓</span>
                  {f}
                </li>
              ))}
              {tier.requires_vpn && (
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 text-emerald-600">✓</span>
                  Dedicated VPC + site-to-site VPN
                </li>
              )}
            </ul>

            <Link
              href={`/pricing/checkout?tier=${tier.tier_key}`}
              className="mt-6 rounded-lg bg-slate-900 px-4 py-2 text-center text-sm font-medium text-white hover:bg-slate-700"
            >
              Get started
            </Link>
          </div>
        ))}
      </div>
    </main>
  );
}
