"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiClient } from "@/lib/api-client";

type CheckoutResponse = {
  checkout_url: string;
  provisioning_request_id: number;
};

type SlugAvailability = {
  slug: string;
  available: boolean;
  reason: string | null;
};

/** Lowercase, hyphenate, and strip anything that isn't a-z/0-9/hyphen. */
function sanitizeSlug(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Derive a URL-safe slug from a free-text company name. */
function slugifyCompanyName(name: string): string {
  return sanitizeSlug(name).slice(0, 64);
}

function slugPreviewHost(): string {
  if (typeof window !== "undefined") return window.location.host;
  return "app.tablescope.cloud";
}

function CheckoutForm() {
  const params = useSearchParams();
  const tierKey = params.get("tier") || "basic_cloud";

  const [companyName, setCompanyName] = useState("");
  const [tenantSlug, setTenantSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [confirmEmail, setConfirmEmail] = useState("");
  const [billingEmail, setBillingEmail] = useState("");
  const [street, setStreet] = useState("");
  const [city, setCity] = useState("");
  const [stateRegion, setStateRegion] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [interval, setInterval] = useState<"month" | "year">("month");
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [slugStatus, setSlugStatus] = useState<
    "idle" | "checking" | "available" | "taken"
  >("idle");
  const [slugMessage, setSlugMessage] = useState<string | null>(null);

  // Auto-derive the slug from the company name until the user edits it.
  useEffect(() => {
    if (!slugEdited) {
      setTenantSlug(slugifyCompanyName(companyName));
    }
  }, [companyName, slugEdited]);

  // Debounced slug-availability check.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const checkSlug = useCallback((slug: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (slug.length < 2) {
      setSlugStatus("idle");
      setSlugMessage(null);
      return;
    }
    setSlugStatus("checking");
    setSlugMessage(null);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await apiClient.get<SlugAvailability>(
          `/api/billing/tenant-slug-availability?slug=${encodeURIComponent(slug)}`,
        );
        // Ignore stale responses if the slug changed while we waited.
        if (res.slug !== slug) return;
        setSlugStatus(res.available ? "available" : "taken");
        setSlugMessage(
          res.available ? "This workspace URL is available." : res.reason,
        );
      } catch {
        setSlugStatus("idle");
        setSlugMessage(null);
      }
    }, 400);
  }, []);

  useEffect(() => {
    checkSlug(tenantSlug);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [tenantSlug, checkSlug]);

  const emailsMatch =
    confirmEmail.trim().toLowerCase() === adminEmail.trim().toLowerCase();
  const emailMismatch = confirmEmail.length > 0 && !emailsMatch;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!agreed) {
      setError("Please accept the terms to continue.");
      return;
    }
    if (!emailsMatch) {
      setError("Admin email and confirmation email must match.");
      return;
    }
    if (slugStatus === "taken") {
      setError("That workspace URL is already taken. Please choose another.");
      return;
    }
    setLoading(true);
    try {
      const res = await apiClient.post<CheckoutResponse>(
        "/api/billing/checkout/session",
        {
          tier_key: tierKey,
          company_name: companyName,
          tenant_name: companyName,
          tenant_slug: tenantSlug,
          tenant_admin_first_name: firstName || null,
          tenant_admin_last_name: lastName || null,
          tenant_admin_phone: phone || null,
          tenant_admin_email: adminEmail,
          confirm_admin_email: confirmEmail || adminEmail,
          billing_email: billingEmail || null,
          company_street: street || null,
          company_city: city || null,
          company_state: stateRegion || null,
          company_postal_code: postalCode || null,
          region: "us-west-2",
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

  const slugValid = slugStatus !== "taken";
  const canSubmit =
    !loading &&
    Boolean(companyName) &&
    Boolean(tenantSlug) &&
    Boolean(adminEmail) &&
    emailsMatch &&
    agreed &&
    slugValid;

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
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
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className={label}>Company name</label>
            <input
              className={input}
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              required
            />
          </div>
          <div>
            <label className={label}>Workspace slug</label>
            <input
              className={input}
              value={tenantSlug}
              onChange={(e) => {
                setSlugEdited(true);
                setTenantSlug(sanitizeSlug(e.target.value));
              }}
              placeholder="acme-co"
              required
            />
            <p className="mt-1 text-xs text-slate-500">
              https://{slugPreviewHost()}/{tenantSlug || "your-workspace"}
            </p>
            {slugStatus === "checking" && (
              <p className="mt-1 text-xs text-slate-400">Checking availability…</p>
            )}
            {slugStatus === "available" && (
              <p className="mt-1 text-xs text-green-600">{slugMessage}</p>
            )}
            {slugStatus === "taken" && (
              <p className="mt-1 text-xs text-red-600">{slugMessage}</p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
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
          <div>
            <label className={label}>Phone number</label>
            <input
              type="tel"
              className={input}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+1 555 123 4567"
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
          <label className={label}>Confirm admin email</label>
          <input
            type="email"
            className={input}
            value={confirmEmail}
            onChange={(e) => setConfirmEmail(e.target.value)}
            required
          />
          {emailMismatch && (
            <p className="mt-1 text-xs text-red-600">
              Emails do not match.
            </p>
          )}
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

        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <div className="md:col-span-2">
            <label className={label}>Street</label>
            <input
              className={input}
              value={street}
              onChange={(e) => setStreet(e.target.value)}
            />
          </div>
          <div>
            <label className={label}>City</label>
            <input
              className={input}
              value={city}
              onChange={(e) => setCity(e.target.value)}
            />
          </div>
          <div>
            <label className={label}>State</label>
            <input
              className={input}
              value={stateRegion}
              onChange={(e) => setStateRegion(e.target.value)}
            />
          </div>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <div>
            <label className={label}>Postal code</label>
            <input
              className={input}
              value={postalCode}
              onChange={(e) => setPostalCode(e.target.value)}
            />
          </div>
        </div>

        <div>
          <label className={label}>Billing interval</label>
          <select
            className={`${input} md:max-w-xs`}
            value={interval}
            onChange={(e) => setInterval(e.target.value as "month" | "year")}
          >
            <option value="month">Monthly</option>
            <option value="year">Annual</option>
          </select>
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
          disabled={!canSubmit}
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
