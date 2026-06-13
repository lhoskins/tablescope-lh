"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  exchangeWithSupabase,
  exchangeWithClerk,
  loginWithPassword,
  readSupabaseTokenFromHash,
  storeToken,
  storeUserMeta,
} from "@/lib/auth";

type AuthMethod = "password" | "supabase" | "clerk";

export default function TenantLoginPage() {
  const router = useRouter();
  const params = useParams<{ slug: string }>();
  const tenantSlug = params.slug;

  const [method, setMethod] = useState<AuthMethod>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const accessToken = readSupabaseTokenFromHash();
    if (!accessToken) return;
    setLoading(true);
    exchangeWithSupabase(accessToken, tenantSlug)
      .then((result) => {
        storeToken(result.access_token);
        storeUserMeta({
          role: result.role,
          is_super_admin: result.is_super_admin,
          tenant_id: result.tenant_id,
          user_id: result.user_id,
          tenant_slug: result.tenant_slug,
        });
        router.replace("/dashboard");
      })
      .catch((err) => {
        setError((err as Error).message);
        setMethod("supabase");
        setLoading(false);
      });
  }, [router, tenantSlug]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result =
        method === "password"
          ? await loginWithPassword(email, password, tenantSlug)
          : method === "clerk"
            ? await exchangeWithClerk(token, tenantSlug)
            : await exchangeWithSupabase(token, tenantSlug);
      storeToken(result.access_token);
      storeUserMeta({
        role: result.role,
        is_super_admin: result.is_super_admin,
        tenant_id: result.tenant_id,
        user_id: result.user_id,
        tenant_slug: result.tenant_slug,
      });
      router.replace("/dashboard");
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
            Auth method
          </label>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as AuthMethod)}
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
          >
            <option value="password">Email &amp; Password</option>
            <option value="supabase">Supabase</option>
            <option value="clerk">Clerk</option>
          </select>
        </div>

        {method === "password" ? (
          <>
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
          </>
        ) : (
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Provider access token (JWT)
            </label>
            <textarea
              value={token}
              onChange={(e) => setToken(e.target.value)}
              rows={5}
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm font-mono"
              placeholder="eyJhbGciOi..."
            />
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={
            loading ||
            (method === "password" ? !email || !password : !token)
          }
          className="w-full rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg disabled:opacity-50"
        >
          {loading ? "Signing in\u2026" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
