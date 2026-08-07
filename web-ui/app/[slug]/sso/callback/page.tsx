"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  exchangeWithSupabase,
  readSupabaseTokenFromHash,
  storeToken,
  storeUserMeta,
  type ExchangeResponse,
} from "@/lib/auth";

export default function SsoCallbackPage() {
  const router = useRouter();
  const params = useParams<{ slug: string }>();
  const searchParams = useSearchParams();
  const tenantSlug = params.slug;

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantSlug) {
      setError("Missing tenant slug in callback URL.");
      return;
    }

    const ssoError = searchParams.get("error");
    if (ssoError) {
      setError(ssoError);
      return;
    }

    const accessToken = readSupabaseTokenFromHash();
    if (!accessToken) {
      setError("No SSO access token found in callback URL.");
      return;
    }

    exchangeWithSupabase(accessToken, tenantSlug)
      .then((result: ExchangeResponse) => {
        storeToken(result.access_token);
        storeUserMeta({
          role: result.role,
          is_super_admin: result.is_super_admin,
          tenant_id: result.tenant_id,
          user_id: result.user_id,
          tenant_slug: result.tenant_slug,
        });
        const next = searchParams.get("next");
        router.replace(
          next && next.startsWith("/") && !next.startsWith("//") ? next : "/",
        );
      })
      .catch((err) => setError((err as Error).message));
  }, [router, searchParams, tenantSlug]);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="mb-2 text-2xl font-semibold text-slate-900">
        Completing sign-in…
      </h1>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </main>
  );
}
