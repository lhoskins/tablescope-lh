"use client";

import { useCallback, useEffect, useState } from "react";
import { IconLoader2, IconShieldCheck, IconShieldOff } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { PhoneMfaForm } from "@/components/auth/phone-mfa-form";
import {
  getMfaStatus,
  getVerifiedPhoneFactor,
  refreshTablescopeSession,
  unenrollPhone,
  type MfaStatus,
  type PhoneFactor,
} from "@/lib/mfa";
import { getUserMeta } from "@/lib/auth";

/**
 * Profile → Security: SMS multi-factor authentication. Admin-tier roles must
 * keep a verified phone; members may optionally add one. Shows current status,
 * an add-phone flow, and a remove action.
 */
export function MfaSecuritySection() {
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [factor, setFactor] = useState<PhoneFactor | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, f] = await Promise.all([
        getMfaStatus().catch(() => null),
        getVerifiedPhoneFactor().catch(() => null),
      ]);
      setStatus(s);
      setFactor(f);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onVerified() {
    setAdding(false);
    setNote("SMS verification enabled.");
    const meta = getUserMeta();
    try {
      await refreshTablescopeSession(meta?.tenant_slug ?? null);
    } catch {
      /* token refresh best-effort */
    }
    await load();
  }

  async function onRemove() {
    if (!factor) return;
    setBusy(true);
    setError(null);
    try {
      await unenrollPhone(factor.id);
      setNote("SMS verification removed.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const required = status?.roleRequiresMfa ?? false;

  return (
    <section className="space-y-4 rounded-lg border border-line-tertiary bg-bg-primary p-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-h3 text-ink-primary">Two-factor authentication</h2>
          <p className="mt-1 text-small text-ink-tertiary">
            Protect your account with a verification code sent by text message
            (SMS).
          </p>
        </div>
        {factor ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2.5 py-1 text-caption font-medium text-success">
            <IconShieldCheck size={14} /> Enabled
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-bg-secondary px-2.5 py-1 text-caption font-medium text-ink-tertiary">
            <IconShieldOff size={14} /> Off
          </span>
        )}
      </div>

      {loading ? (
        <p className="text-small text-ink-tertiary">
          <IconLoader2 size={14} className="mr-1 inline animate-spin" /> Loading…
        </p>
      ) : (
        <>
          {required && !factor && (
            <p className="rounded-md bg-warning/10 px-3 py-2 text-small text-warning">
              Your role requires SMS verification for access. Add a phone number
              to continue.
            </p>
          )}

          {factor ? (
            <div className="flex items-center justify-between rounded-md border border-line-tertiary px-3 py-2">
              <div className="text-[13px] text-ink-secondary">
                Verified phone{" "}
                <span className="font-medium">{factor.phone ?? "on file"}</span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={onRemove}
                disabled={busy || required}
                title={
                  required
                    ? "Required for your role — cannot be removed"
                    : undefined
                }
              >
                {busy ? <IconLoader2 size={14} className="animate-spin" /> : null}
                Remove
              </Button>
            </div>
          ) : adding ? (
            <PhoneMfaForm mode="setup" onVerified={onVerified} />
          ) : (
            <Button variant="primary" size="md" onClick={() => setAdding(true)}>
              Add phone number
            </Button>
          )}

          {note && <p className="text-small text-success">{note}</p>}
          {error && <p className="text-small text-danger">{error}</p>}
        </>
      )}
    </section>
  );
}
