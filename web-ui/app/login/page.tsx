"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  exchangeWithSupabase,
  exchangeWithClerk,
  loginWithPassword,
  storeToken,
} from "@/lib/auth";

type AuthMethod = "password" | "supabase" | "clerk";

export default function LoginPage() {
  const router = useRouter();
  const [method, setMethod] = useState<AuthMethod>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result =
        method === "password"
          ? await loginWithPassword(email, password)
          : method === "clerk"
            ? await exchangeWithClerk(token)
            : await exchangeWithSupabase(token);
      storeToken(result.access_token);
      router.replace("/dashboard");
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
        Select &quot;Email &amp; Password&quot; for direct login without an
        external auth provider. Supabase and Clerk options exchange a
        third-party JWT via the /api/auth/exchange endpoint.
      </p>
    </main>
  );
}
