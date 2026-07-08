"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiClient } from "@/lib/api-client";

type ProvisioningStatus = {
  status: string;
  tenant_status: string;
  billing_status: string;
  data_plane_status: string;
  vpn_status: string;
  root_admin_status: string;
  tenant_slug: string;
  company_name: string | null;
  tier_key: string;
  requires_vpn: boolean;
  error_message: string | null;
};

const STEPS: { key: string; label: string; done: (s: ProvisioningStatus) => boolean }[] = [
  { key: "payment", label: "Payment confirmed", done: (s) => s.status !== "pending_payment" },
  { key: "tenant", label: "Workspace created", done: (s) => s.tenant_status === "active" },
  {
    key: "admin",
    label: "Administrator account created",
    done: (s) => ["membership_created", "invite_sent"].includes(s.root_admin_status),
  },
  {
    key: "dataplane",
    label: "Data plane provisioned",
    done: (s) =>
      ["provisioned", "shared_cloud_bound", "not_required"].includes(s.data_plane_status),
  },
  {
    key: "invite",
    label: "Setup email sent",
    done: (s) => s.root_admin_status === "invite_sent",
  },
  { key: "ready", label: "Workspace ready", done: (s) => s.status === "provisioned" },
];

function SuccessInner() {
  const params = useSearchParams();
  const sessionId = params.get("session_id");
  const [status, setStatus] = useState<ProvisioningStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setError("Missing checkout session id.");
      return;
    }
    async function poll() {
      try {
        const s = await apiClient.get<ProvisioningStatus>(
          `/api/provisioning/status?session_id=${encodeURIComponent(sessionId!)}`,
        );
        setStatus(s);
        if (s.status === "provisioned" || s.status === "failed") {
          if (timer.current) clearInterval(timer.current);
        }
      } catch (e) {
        setError((e as Error).message);
      }
    }
    poll();
    timer.current = setInterval(poll, 3000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [sessionId]);

  const provisioned = status?.status === "provisioned";
  const companyName = status?.company_name?.trim() || "your";

  return (
    <main className="mx-auto max-w-lg px-6 py-16">
      <h1 className="mb-2 text-2xl font-semibold text-slate-900">
        {provisioned
          ? "Your Tablescope workspace is ready"
          : "Setting up your workspace"}
      </h1>
      {provisioned ? (
        <div className="mb-8 space-y-3 text-sm text-slate-600">
          <p>
            Thank you for your payment. Your {companyName} tenant has finished
            provisioning and your Tablescope workspace is ready.
          </p>
          <p>
            We&apos;ve sent an email to the tenant administrator with
            instructions to finish setting up the account and create a password.
          </p>
          <p>Please check your email to complete setup and sign in.</p>
        </div>
      ) : (
        <p className="mb-8 text-sm text-slate-600">
          Thanks for your payment. We&apos;re provisioning your Tablescope
          workspace. This can take a few minutes.
        </p>
      )}

      {error && (
        <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      {status && (
        <ol className="space-y-3">
          {STEPS.map((step) => {
            const done = status.status === "provisioned" || step.done(status);
            return (
              <li key={step.key} className="flex items-center gap-3">
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                    done ? "bg-emerald-500 text-white" : "bg-slate-200 text-slate-500"
                  }`}
                >
                  {done ? "✓" : "•"}
                </span>
                <span className={done ? "text-slate-900" : "text-slate-500"}>
                  {step.label}
                </span>
              </li>
            );
          })}
        </ol>
      )}

      {status?.status === "failed" && (
        <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          Provisioning hit an error. Our team has been notified.
          {status.error_message ? ` (${status.error_message})` : ""}
        </p>
      )}

      {provisioned && status && (
        <div className="mt-8 space-y-3">
          {status.requires_vpn && status.vpn_status === "awaiting_customer_network_details" && (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Your data plane is ready. After you sign in, complete VPN onboarding to
              connect your network.
            </p>
          )}
          <Link
            href={`/login?tenant=${status.tenant_slug}`}
            className="inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Go to login
          </Link>
          <p className="text-sm text-slate-500">
            Didn&apos;t receive the email? Check your spam folder or contact
            Tablescope support.
          </p>
        </div>
      )}
    </main>
  );
}

export default function BillingSuccessPage() {
  return (
    <Suspense fallback={<p className="p-12 text-center text-slate-500">Loading…</p>}>
      <SuccessInner />
    </Suspense>
  );
}
