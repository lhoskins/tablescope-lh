"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PhoneMfaForm } from "@/components/auth/phone-mfa-form";
import { getUserMeta } from "@/lib/auth";
import { getMfaStatus } from "@/lib/mfa";

export default function ChallengePhoneMfaPage() {
  const router = useRouter();
  const [maskedPhone, setMaskedPhone] = useState<string | null>(null);
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
        const status = await getMfaStatus();
        if (!status.hasVerifiedFactor) {
          setState("no-factor");
          router.replace("/mfa/setup-phone");
          return;
        }
        setMaskedPhone(status.maskedPhone);
        setState("ready");
      } catch {
        setState("no-factor");
        router.replace("/mfa/setup-phone");
      }
    })();
  }, [router]);

  function onVerified() {
    // verifyPhone() already stored the aal2 token.
    router.replace("/");
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6">
      <h1 className="mb-2 text-2xl font-semibold text-ink-primary">
        Verify it&apos;s you
      </h1>
      <p className="mb-6 text-sm text-ink-tertiary">
        Enter your phone number to receive a verification code by text message.
      </p>
      {state === "ready" ? (
        <PhoneMfaForm
          mode="challenge"
          maskedPhone={maskedPhone}
          onVerified={onVerified}
        />
      ) : (
        <p className="text-sm text-ink-tertiary">Loading…</p>
      )}
    </main>
  );
}
