"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PhoneMfaForm } from "@/components/auth/phone-mfa-form";
import { getUserMeta } from "@/lib/auth";
import { getMfaStatus } from "@/lib/mfa";

export default function SetupPhoneMfaPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const meta = getUserMeta();
    if (!meta) {
      router.replace("/login");
      return;
    }
    // If a verified factor already exists, this is really a challenge.
    (async () => {
      try {
        const status = await getMfaStatus();
        if (status.hasVerifiedFactor) {
          router.replace("/mfa/challenge-phone");
          return;
        }
      } catch {
        /* ignore — show setup form */
      }
      setReady(true);
    })();
  }, [router]);

  function onVerified() {
    // verifyPhone() already stored the aal2 token.
    router.replace("/");
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6">
      <h1 className="mb-2 text-2xl font-semibold text-ink-primary">
        Set up SMS verification
      </h1>
      <p className="mb-6 text-sm text-ink-tertiary">
        Administrator access requires multi-factor authentication. Add a mobile
        phone number to receive verification codes by text message.
      </p>
      {ready ? (
        <PhoneMfaForm mode="setup" onVerified={onVerified} />
      ) : (
        <p className="text-sm text-ink-tertiary">Loading…</p>
      )}
    </main>
  );
}
