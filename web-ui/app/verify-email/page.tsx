"use client";

import { Suspense } from "react";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { verifyEmail } from "@/lib/auth";

type Status = "verifying" | "verified" | "error";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<Status>("verifying");
  const [error, setError] = useState<string | null>(null);
  const [tenantSlug, setTenantSlug] = useState<string | null>(null);
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;

    if (!token) {
      setStatus("error");
      setError("This verification link is missing its token.");
      return;
    }

    let cancelled = false;
    async function run() {
      try {
        const result = await verifyEmail(token as string);
        if (cancelled) return;
        setTenantSlug(result.tenant_slug);
        setStatus("verified");
      } catch (err) {
        if (cancelled) return;
        setError(
          (err as Error).message ||
            "This link is invalid or has expired. Ask your administrator to resend the invitation.",
        );
        setStatus("error");
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 text-center">
      {status === "verifying" && (
        <>
          <h1 className="mb-2 text-2xl font-semibold text-slate-900">
            Confirming your email…
          </h1>
          <p className="text-sm text-slate-600">This will only take a moment.</p>
        </>
      )}

      {status === "verified" && (
        <>
          <h1 className="mb-2 text-2xl font-semibold text-slate-900">
            Email confirmed
          </h1>
          <p className="mb-6 text-sm text-slate-600">
            Your email address has been verified. We&apos;ve sent a separate
            email with a link to create your password and sign in
            {tenantSlug ? (
              <>
                {" "}
                to the <strong>{tenantSlug}</strong> workspace
              </>
            ) : null}
            .
          </p>
          <p className="text-sm text-slate-500">
            You can close this page once you receive that email.
          </p>
        </>
      )}

      {status === "error" && (
        <>
          <h1 className="mb-2 text-2xl font-semibold text-slate-900">
            We couldn&apos;t verify that link
          </h1>
          <p className="mb-6 text-sm text-red-600">{error}</p>
          <p className="text-sm text-slate-500">
            <Link href="/login" className="text-brand underline">
              Return to sign in
            </Link>
          </p>
        </>
      )}
    </main>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 text-center">
          <h1 className="mb-2 text-2xl font-semibold text-slate-900">
            Confirming your email…
          </h1>
          <p className="text-sm text-slate-600">This will only take a moment.</p>
        </main>
      }
    >
      <VerifyEmailContent />
    </Suspense>
  );
}
