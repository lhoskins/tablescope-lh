"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PhoneMfaForm } from "@/components/auth/phone-mfa-form";
import { getUserMeta } from "@/lib/auth";
import {
  getVerifiedPhoneFactor,
  refreshTablescopeSession,
  type PhoneFactor,
} from "@/lib/mfa";

export default function ChallengePhoneMfaPage() {
  const router = useRouter();
  const [factor, setFactor] = useState<PhoneFactor | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "no-factor">(
    "loading",
  );

  useEffect(() => {
    const meta = getUserMeta();
    if (!meta) {
      router.replace("/login");
      return;
    }
    (async () => {
      try {
        const f = await getVerifiedPhoneFactor();
        if (!f) {
          router.replace("/mfa/setup-phone");
          setState("no-factor");
          return;
        }
        setFactor(f);
        setState("ready");
      } catch {
        setState("no-factor");
        router.replace("/mfa/setup-phone");
      }
    })();
  }, [router]);

  async function onVerified() {
    const meta = getUserMeta();
    await refreshTablescopeSession(meta?.tenant_slug ?? null);
    router.replace("/");
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="mb-2 text-2xl font-semibold text-ink-primary">
        Verify it&apos;s you
      </h1>
      <p className="mb-6 text-sm text-ink-tertiary">
        Enter the verification code we sent by text message to continue.
      </p>
      {state === "ready" && factor ? (
        <PhoneMfaForm
          mode="challenge"
          factorId={factor.id}
          maskedPhone={factor.phone}
          onVerified={onVerified}
        />
      ) : (
        <p className="text-sm text-ink-tertiary">Loading…</p>
      )}
    </main>
  );
}
