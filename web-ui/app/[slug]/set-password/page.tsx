"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import {
  hasSupabaseSession,
  setPasswordAndExchange,
  storeToken,
  storeUserMeta,
  verifyRecoveryToken,
} from "@/lib/auth";

export default function SetPasswordPage() {
  const router = useRouter();
  const params = useParams<{ slug: string }>();
  const searchParams = useSearchParams();
  const tenantSlug = params.slug;

  const [ready, setReady] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // The invite/recovery link establishes a Supabase session either from a URL
  // hash fragment (magic link) or from a token_hash passed in the query string
  // (Tablescope-branded reset email).
  useEffect(() => {
    let cancelled = false;
    async function check() {
      const tokenHash = searchParams.get("token_hash");
      const type = searchParams.get("type");
      if (tokenHash && type === "recovery") {
        try {
          await verifyRecoveryToken(tokenHash);
        } catch (err) {
          if (!cancelled) {
            setError(
              (err as Error).message ||
                "This link is invalid or has expired. Request a new one from the sign-in page.",
            );
          }
          return;
        }
      } else {
        // Wait for supabase-js to detect the session from a magic/recovery hash.
        for (let i = 0; i < 20; i += 1) {
          if (cancelled) return;
          if (await hasSupabaseSession()) {
            if (!cancelled) setReady(true);
            return;
          }
          await new Promise((r) => setTimeout(r, 150));
        }
      }
      if (cancelled) return;
      if (await hasSupabaseSession()) {
        setReady(true);
      } else {
        setError(
          "This link is invalid or has expired. Request a new one from the sign-in page.",
        );
      }
    }
    void check();
    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    try {
      const result = await setPasswordAndExchange(password, tenantSlug);
      storeToken(result.access_token);
      storeUserMeta({
        role: result.role,
        is_super_admin: result.is_super_admin,
        tenant_id: result.tenant_id,
        user_id: result.user_id,
        tenant_slug: result.tenant_slug,
      });
      router.replace(`/${result.tenant_slug || tenantSlug || ""}`);
    } catch (err) {
      setError((err as Error).message);
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="mb-2 text-2xl font-semibold text-slate-900">
        Set your password
      </h1>
      <p className="mb-6 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-700">
        Tenant: <strong>{tenantSlug}</strong>
      </p>

      {!ready && !error && (
        <p className="text-sm text-slate-600">Verifying your link\u2026</p>
      )}

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {ready && (
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              New password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
              placeholder="At least 8 characters"
              autoComplete="new-password"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Confirm password
            </label>
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
              placeholder="Re-enter your password"
              autoComplete="new-password"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !password || !confirm}
            className="w-full rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg disabled:opacity-50"
          >
            {loading ? "Saving\u2026" : "Set password & sign in"}
          </button>
        </form>
      )}
    </main>
  );
}
