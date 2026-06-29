"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getMfaStatus, getVerifiedPhoneFactor } from "@/lib/mfa";
import { getUserMeta } from "@/lib/auth";

/**
 * Backend-backed MFA gate. Rendered inside the app shell, it checks whether the
 * caller's role requires SMS MFA and whether the current session satisfies it.
 * Admin-tier roles without aal2 are redirected to setup (no verified factor) or
 * challenge (factor exists). Renders nothing; enforcement also exists on the
 * backend, so this is purely a UX redirect.
 */
export function MfaGate() {
  const router = useRouter();
  const pathname = usePathname();
  const checked = useRef(false);

  useEffect(() => {
    if (checked.current) return;
    if (!getUserMeta()) return;
    // Never bounce while already on an MFA page.
    if (pathname?.startsWith("/mfa")) return;
    checked.current = true;

    (async () => {
      try {
        const status = await getMfaStatus();
        if (!status.roleRequiresMfa || status.mfaSatisfied) return;
        let hasFactor = false;
        try {
          hasFactor = (await getVerifiedPhoneFactor()) !== null;
        } catch {
          hasFactor = false;
        }
        router.replace(hasFactor ? "/mfa/challenge-phone" : "/mfa/setup-phone");
      } catch {
        /* Status check failed (e.g. offline) — backend still enforces. */
      }
    })();
  }, [router, pathname]);

  return null;
}
