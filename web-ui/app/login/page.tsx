"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { exchangeWithSupabase, exchangeWithClerk, storeToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [provider, setProvider] = useState<"supabase" | "clerk">("supabase");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result =
        provider === "clerk"
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
            Auth provider
          </label>
          <select
            value={provider}
            onChange={(e) =>
              setProvider(e.target.value as "supabase" | "clerk")
            }
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
          >
            <option value="supabase">Supabase</option>
            <option value="clerk">Clerk</option>
          </select>
        </div>
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
        {error && (
          <p className="text-sm text-red-600">{error}</p>
        )}
        <button
          type="submit"
          disabled={loading || !token}
          className="w-full rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg disabled:opacity-50"
        >
          {loading ? "Exchanging…" : "Sign in"}
        </button>
      </form>
      <p className="mt-6 text-xs text-slate-500">
        Tip: the provider token is exchanged for a Tablescope access token
        via the platform-api /api/auth/exchange endpoint. Full SSO is wired
        through Clerk and Supabase JS SDKs when configured in .env.
      </p>
    </main>
  );
}
