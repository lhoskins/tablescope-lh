"use client";

import { useEffect, useState } from "react";
import { IconLoader2 } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { startPhone, verifyPhone } from "@/lib/mfa";
import { PhoneInput } from "./phone-input";
import { OtpInput } from "./otp-input";
import { formatNational, normalizePhone, type CountryCode } from "@/lib/phone";

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
 * Shared phone-SMS MFA form (Twilio Verify). The user selects a country and
 * enters a national phone number; the form normalizes to E.164 before calling
 * the backend. On success the backend returns an aal2 token (stored by
 * `verifyPhone`). In challenge mode the enrolled number is re-entered (we never
 * store it in the clear); the masked form is shown as a hint.
 */
export function PhoneMfaForm({
  mode,
  maskedPhone,
  onVerified,
}: PhoneMfaFormProps) {
  const [step, setStep] = useState<Step>("phone");
  const [countryIso, setCountryIso] = useState<string>("US");
  const [nationalDigits, setNationalDigits] = useState("");
  const [normalizedPhone, setNormalizedPhone] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  function computeNormalized(): string | null {
    const display = formatNational(countryIso as CountryCode, nationalDigits);
    return normalizePhone(countryIso as CountryCode, display);
  }

  async function sendCode(targetPhone: string) {
    const res = await startPhone(targetPhone);
    setStep("code");
    setCooldown(res.cooldownSeconds || 60);
  }

  async function onSubmitPhone(e: React.FormEvent) {
    e.preventDefault();
    const normalized = computeNormalized();
    if (!normalized) {
      setError("Enter a valid phone number for the selected country.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setNormalizedPhone(normalized);
      await sendCode(normalized);
    } catch (err) {
      setError(friendly((err as Error).message));
    } finally {
      setBusy(false);
    }
  }

  async function onResend() {
    if (cooldown > 0 || !normalizedPhone) return;
    setBusy(true);
    setError(null);
    try {
      await sendCode(normalizedPhone);
    } catch (err) {
      setError(friendly((err as Error).message));
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitCode(e: React.FormEvent) {
    e.preventDefault();
    if (!normalizedPhone) {
      setError("Phone number is missing. Please start over.");
      return;
    }
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code from the text message.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await verifyPhone(normalizedPhone, code.trim());
      await onVerified();
    } catch (err) {
      setError(friendly((err as Error).message));
      setBusy(false);
    }
  }

  const hint =
    mode === "challenge" && maskedPhone
      ? `Enter the phone number on file (ending ${maskedPhone}). Standard messaging rates may apply.`
      : "We'll text a verification code to this number. Standard messaging rates may apply.";

  return (
    <div className="space-y-4">
      {step === "phone" ? (
        <form onSubmit={onSubmitPhone} className="space-y-4">
          <PhoneInput
            countryIso={countryIso}
            nationalDigits={nationalDigits}
            onCountryChange={setCountryIso}
            onNationalChange={setNationalDigits}
            label="Mobile phone number"
            hint={hint}
            error={error}
            disabled={busy}
          />
          <Button type="submit" variant="primary" size="md" disabled={busy}>
            {busy && <IconLoader2 size={14} className="animate-spin" />}
            Send code
          </Button>
        </form>
      ) : (
        <form onSubmit={onSubmitCode} className="space-y-4">
          <p className="text-small text-ink-tertiary">
            Code sent to{" "}
            <span className="font-medium">{maskedPhone ?? normalizedPhone}</span>.
          </p>
          <OtpInput
            value={code}
            onChange={setCode}
            label="Verification code"
            autoFocus
            disabled={busy}
            error={Boolean(error)}
          />
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
              aria-live="polite"
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
