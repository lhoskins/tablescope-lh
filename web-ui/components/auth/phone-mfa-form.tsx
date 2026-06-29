"use client";

import { useEffect, useState } from "react";
import { IconLoader2 } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import {
  challengePhone,
  enrollPhone,
  verifyPhone,
} from "@/lib/mfa";

const RESEND_COOLDOWN_SECONDS = 60;
const E164 = /^\+[1-9]\d{7,14}$/;

export type PhoneMfaMode = "setup" | "challenge";

export interface PhoneMfaFormProps {
  mode: PhoneMfaMode;
  /** For challenge mode: the verified factor to challenge. */
  factorId?: string;
  /** Masked phone to display in challenge mode (e.g. +1******1212). */
  maskedPhone?: string | null;
  /** Called after a successful verify (factor enrolled + session aal2). */
  onVerified: () => void | Promise<void>;
}

type Step = "phone" | "code";

/**
 * Shared phone-SMS MFA form. In setup mode the user enters an E.164 number,
 * receives a code (Supabase enroll + challenge -> backend Twilio hook), and
 * verifies it. In challenge mode the verified factor is challenged directly.
 */
export function PhoneMfaForm({
  mode,
  factorId: existingFactorId,
  maskedPhone,
  onVerified,
}: PhoneMfaFormProps) {
  const [step, setStep] = useState<Step>(mode === "challenge" ? "code" : "phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [factorId, setFactorId] = useState<string | null>(
    existingFactorId ?? null,
  );
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  // Auto-send the first challenge when entering challenge mode.
  useEffect(() => {
    if (mode === "challenge" && existingFactorId && !challengeId) {
      void sendCode(existingFactorId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, existingFactorId]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  async function sendCode(targetFactorId: string) {
    setBusy(true);
    setError(null);
    try {
      const cid = await challengePhone(targetFactorId);
      setChallengeId(cid);
      setStep("code");
      setCooldown(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      setError(friendly((err as Error).message));
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitPhone(e: React.FormEvent) {
    e.preventDefault();
    if (!E164.test(phone)) {
      setError("Enter a phone number in international format, e.g. +16615551212.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const id = await enrollPhone(phone);
      setFactorId(id);
      await sendCode(id);
    } catch (err) {
      setError(friendly((err as Error).message));
      setBusy(false);
    }
  }

  async function onResend() {
    if (cooldown > 0 || !factorId) return;
    await sendCode(factorId);
  }

  async function onSubmitCode(e: React.FormEvent) {
    e.preventDefault();
    if (!factorId || !challengeId) {
      setError("No active challenge. Resend a code and try again.");
      return;
    }
    if (!/^\d{4,8}$/.test(code.trim())) {
      setError("Enter the numeric code from the text message.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await verifyPhone(factorId, challengeId, code.trim());
      await onVerified();
    } catch (err) {
      setError(friendly((err as Error).message));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {step === "phone" ? (
        <form onSubmit={onSubmitPhone} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-ink-secondary">
              Mobile phone number
            </label>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+16615551212"
              autoComplete="tel"
              className="w-full rounded-md border border-line-tertiary px-3 py-2 text-sm"
            />
            <p className="mt-1 text-caption text-ink-tertiary">
              We&apos;ll text a verification code to this number. Standard
              messaging rates may apply.
            </p>
          </div>
          {error && <p className="text-small text-danger">{error}</p>}
          <Button type="submit" variant="primary" size="md" disabled={busy}>
            {busy && <IconLoader2 size={14} className="animate-spin" />}
            Send code
          </Button>
        </form>
      ) : (
        <form onSubmit={onSubmitCode} className="space-y-4">
          {maskedPhone && (
            <p className="text-small text-ink-tertiary">
              Code sent to <span className="font-medium">{maskedPhone}</span>.
            </p>
          )}
          <div>
            <label className="mb-1 block text-sm font-medium text-ink-secondary">
              Verification code
            </label>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/[^\d]/g, ""))}
              placeholder="123456"
              className="w-full rounded-md border border-line-tertiary px-3 py-2 text-sm tracking-widest"
            />
          </div>
          {error && <p className="text-small text-danger">{error}</p>}
          <div className="flex items-center gap-3">
            <Button type="submit" variant="primary" size="md" disabled={busy}>
              {busy && <IconLoader2 size={14} className="animate-spin" />}
              Verify
            </Button>
            <button
              type="button"
              onClick={onResend}
              disabled={cooldown > 0 || busy}
              className="text-small text-brand-700 underline disabled:text-ink-tertiary disabled:no-underline"
            >
              {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/** Map raw Supabase / rate-limit errors to user-friendly copy. */
function friendly(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("invalid") && m.includes("code")) {
    return "That code is incorrect or expired. Request a new one and try again.";
  }
  if (m.includes("rate") || m.includes("too many") || m.includes("429")) {
    return "Too many requests. Please wait a minute before requesting another code.";
  }
  if (m.includes("expired")) {
    return "That code has expired. Request a new one.";
  }
  return message || "Something went wrong. Please try again.";
}
