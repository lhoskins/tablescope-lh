"use client";

import { useEffect, useState } from "react";
import { IconLoader2 } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { startPhone, verifyPhone } from "@/lib/mfa";

const E164 = /^\+[1-9]\d{7,14}$/;

export type PhoneMfaMode = "setup" | "challenge";

export interface PhoneMfaFormProps {
  mode: PhoneMfaMode;
  /** Masked phone to display in challenge mode (e.g. +1******1212). */
  maskedPhone?: string | null;
  /** Called after a successful verify (factor enrolled + session aal2). */
  onVerified: () => void | Promise<void>;
}

type Step = "phone" | "code";

/**
 * Shared phone-SMS MFA form (Twilio Verify). The user enters an E.164 number,
 * the backend sends a code via Twilio Verify, and the entered code is checked.
 * On success the backend returns an aal2 token (stored by `verifyPhone`). In
 * challenge mode the enrolled number must be re-entered (we never store it in
 * the clear); the masked form is shown as a hint.
 */
export function PhoneMfaForm({
  mode,
  maskedPhone,
  onVerified,
}: PhoneMfaFormProps) {
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  async function sendCode(targetPhone: string) {
    const res = await startPhone(targetPhone);
    setStep("code");
    setCooldown(res.cooldownSeconds || 60);
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
      await sendCode(phone);
    } catch (err) {
      setError(friendly((err as Error).message));
    } finally {
      setBusy(false);
    }
  }

  async function onResend() {
    if (cooldown > 0 || !phone) return;
    setBusy(true);
    setError(null);
    try {
      await sendCode(phone);
    } catch (err) {
      setError(friendly((err as Error).message));
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitCode(e: React.FormEvent) {
    e.preventDefault();
    if (!/^\d{4,8}$/.test(code.trim())) {
      setError("Enter the numeric code from the text message.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await verifyPhone(phone, code.trim());
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
              {mode === "challenge" && maskedPhone
                ? `Enter the phone number on file (ending ${maskedPhone}). `
                : "We'll text a verification code to this number. "}
              Standard messaging rates may apply.
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
          <p className="text-small text-ink-tertiary">
            Code sent to{" "}
            <span className="font-medium">{maskedPhone ?? phone}</span>.
          </p>
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

/** Map raw API / rate-limit errors to user-friendly copy. */
function friendly(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("incorrect") || (m.includes("code") && m.includes("expired"))) {
    return "That code is incorrect or expired. Request a new one and try again.";
  }
  if (m.includes("rate") || m.includes("too many") || m.includes("429")) {
    return "Too many requests. Please wait a minute before requesting another code.";
  }
  if (m.includes("expired")) {
    return "That code has expired. Request a new one.";
  }
  if (m.includes("match")) {
    return "This number doesn't match the phone on file for your account.";
  }
  return message || "Something went wrong. Please try again.";
}
