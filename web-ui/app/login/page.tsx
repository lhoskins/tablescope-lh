"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import {
  exchangeWithSupabase,
  exchangeWithClerk,
  loginWithPassword,
  readSupabaseTokenFromHash,
  storeToken,
  storeUserMeta,
} from "@/lib/auth";

type AuthMethod = "password" | "supabase" | "clerk";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantParam = searchParams.get("tenant");
  // Path the user was trying to reach before being bounced to login. Only
  // same-origin relative paths are honored to avoid open-redirects.
  const nextParam = searchParams.get("next");
  const destination =
    nextParam && nextParam.startsWith("/") && !nextParam.startsWith("//")
      ? nextParam
      : "/";

  const [method, setMethod] = useState<AuthMethod>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantSlug, setTenantSlug] = useState(tenantParam || "");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // The generic /login page is meant for choosing a tenant. When a tenant is
    // already supplied, send the user to the dedicated /:tenant/login page,
    // which has fewer options and avoids the ambiguous "Signing in" message.
    if (tenantParam && typeof window !== "undefined" && !window.location.hash.includes("access_token")) {
      const next = nextParam ? `?next=${encodeURIComponent(nextParam)}` : "";
      router.replace(`/${tenantParam}/login${next}`);
    }
  }, [tenantParam, nextParam, router]);

  useEffect(() => {
    const accessToken = readSupabaseTokenFromHash();
    if (!accessToken) return;
    setLoading(true);
    exchangeWithSupabase(accessToken, tenantParam || undefined)
      .then((result) => {
        storeToken(result.access_token);
        storeUserMeta({
          role: result.role,
          is_super_admin: result.is_super_admin,
          tenant_id: result.tenant_id,
          user_id: result.user_id,
          tenant_slug: result.tenant_slug,
        });
        router.replace(destination);
      })
      .catch((err) => {
        setError((err as Error).message);
        setMethod("supabase");
        setLoading(false);
      });
  }, [router, tenantParam, destination]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const slug = tenantSlug.trim() || undefined;
      const result =
        method === "password"
          ? await loginWithPassword(email, password, slug)
          : method === "clerk"
            ? await exchangeWithClerk(token, slug)
            : await exchangeWithSupabase(token, slug);
      storeToken(result.access_token);
      storeUserMeta({
        role: result.role,
        is_super_admin: result.is_super_admin,
        tenant_id: result.tenant_id,
        user_id: result.user_id,
        tenant_slug: result.tenant_slug,
      });
      router.replace(destination);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="mb-6 text-2xl font-semibold text-slate-900">
        Sign in to Tablescope
      </h1>
      {tenantParam && (
        <p className="mb-4 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-700">
          Sign in to tenant: <strong>{tenantParam}</strong>
        </p>
      )}
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

        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            Tenant (optional)
          </label>
          <input
            type="text"
            value={tenantSlug}
            onChange={(e) =>
              setTenantSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))
            }
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
            placeholder="Leave blank for default tenant"
          />
          <p className="mt-1 text-xs text-slate-400">
            Tenant slug — e.g. &quot;acme-corp&quot;. Leave blank for the default tenant.
          </p>
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
                placeholder="admin@tablescope.local"
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
      <p className="mt-6 text-xs text-slate-500">
        To sign into a specific tenant, use{" "}
        <code className="rounded bg-slate-100 px-1 py-0.5">
          /your-slug/login
        </code>{" "}
        or enter the tenant slug above.
      </p>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
