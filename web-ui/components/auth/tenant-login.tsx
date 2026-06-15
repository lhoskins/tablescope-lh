"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  exchangeWithSupabase,
  loginWithPassword,
  readSupabaseTokenFromHash,
  requestPasswordReset,
  storeToken,
  storeUserMeta,
} from "@/lib/auth";

export function TenantLogin({ slug }: { slug: string }) {
  const router = useRouter();
  const tenantSlug = slug;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function finishLogin(result: Awaited<ReturnType<typeof loginWithPassword>>) {
    storeToken(result.access_token);
    storeUserMeta({
      role: result.role,
      is_super_admin: result.is_super_admin,
      tenant_id: result.tenant_id,
      user_id: result.user_id,
      tenant_slug: result.tenant_slug,
    });
    router.replace("/");
  }

  // Auto sign-in when arriving from a magic/invite link (token in URL hash).
  useEffect(() => {
    const accessToken = readSupabaseTokenFromHash();
    if (!accessToken) return;
    setLoading(true);
    exchangeWithSupabase(accessToken, tenantSlug)
      .then(finishLogin)
      .catch((err) => {
        setError((err as Error).message);
        setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router, tenantSlug]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setLoading(true);
    try {
      finishLogin(await loginWithPassword(email, password, tenantSlug));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function onForgotPassword() {
    setError(null);
    setNotice(null);
    if (!email) {
      setError("Enter your email above first, then click \u201cForgot password\u201d.");
      return;
    }
    setLoading(true);
    try {
      await requestPasswordReset(email, tenantSlug);
      setNotice(
        "If that email has an account, a password-reset link is on its way.",
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="mb-2 text-2xl font-semibold text-slate-900">
        Sign in to Tablescope
      </h1>
      <p className="mb-6 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-700">
        Tenant: <strong>{tenantSlug}</strong>
      </p>
      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
            placeholder="you@company.com"
            autoComplete="email"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
            placeholder="Enter your password"
            autoComplete="current-password"
          />
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {notice && <p className="text-sm text-green-700">{notice}</p>}

        <button
          type="submit"
          disabled={loading || !email || !password}
          className="w-full rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg disabled:opacity-50"
        >
          {loading ? "Signing in\u2026" : "Sign in"}
        </button>

        <button
          type="button"
          onClick={onForgotPassword}
          disabled={loading}
          className="w-full text-center text-sm text-blue-600 hover:underline disabled:opacity-50"
        >
          Forgot password?
        </button>
      </form>
    </main>
  );
}
