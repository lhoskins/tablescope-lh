"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  exchangeWithSupabase,
  getTenantAuthPolicy,
  loginWithPassword,
  readSupabaseTokenFromHash,
  requestPasswordReset,
  startSso,
  storeToken,
  storeUserMeta,
  type TenantAuthPolicy,
  type ExchangeResponse,
} from "@/lib/auth";

export function TenantLogin({ slug }: { slug: string }) {
  // useSearchParams requires a Suspense boundary during prerender.
  return (
    <Suspense>
      <TenantLoginInner slug={slug} />
    </Suspense>
  );
}

function TenantLoginInner({ slug }: { slug: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = slug;
  // Path the user was trying to reach before being bounced to login. Only
  // same-origin relative paths are honored to avoid open-redirects.
  const nextParam = searchParams.get("next");
  const destination =
    nextParam && nextParam.startsWith("/") && !nextParam.startsWith("//")
      ? nextParam
      : "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [policy, setPolicy] = useState<TenantAuthPolicy | null>(null);
  const [policyLoading, setPolicyLoading] = useState(true);

  useEffect(() => {
    getTenantAuthPolicy(tenantSlug)
      .then(setPolicy)
      .catch(() => setPolicy(null))
      .finally(() => setPolicyLoading(false));
  }, [tenantSlug]);

  function finishLogin(result: ExchangeResponse) {
    storeToken(result.access_token);
    storeUserMeta({
      role: result.role,
      is_super_admin: result.is_super_admin,
      tenant_id: result.tenant_id,
      user_id: result.user_id,
      tenant_slug: result.tenant_slug,
    });
    router.replace(destination);
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

  async function onSso() {
    setError(null);
    setLoading(true);
    try {
      const { redirect_url } = await startSso(tenantSlug, destination);
      window.location.href = redirect_url;
    } catch (err) {
      setError((err as Error).message);
      setLoading(false);
    }
  }

  const ssoEnabled = policy?.sso_enabled ?? false;
  const ssoRequired = policy?.sso_required ?? false;
  const localAllowed = policy?.local_login_allowed ?? true;

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="mb-2 text-2xl font-semibold text-slate-900">
        Sign in to Tablescope
      </h1>
      <p className="mb-6 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-700">
        Tenant: <strong>{tenantSlug}</strong>
      </p>

      {policyLoading ? (
        <p className="text-sm text-slate-600">Loading tenant sign-in options…</p>
      ) : (
        <>
          {ssoEnabled && (
            <button
              type="button"
              onClick={onSso}
              disabled={loading}
              className="mb-4 w-full rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {loading ? "Redirecting…" : (policy?.sso_button_label || "Sign in with SSO")}
            </button>
          )}

          {(!ssoRequired || localAllowed) && (
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
          )}

          {ssoRequired && !localAllowed && !ssoEnabled && (
            <p className="text-sm text-red-600">
              This tenant requires SSO, but no SSO provider is configured.
            </p>
          )}
        </>
      )}
    </main>
  );
}
