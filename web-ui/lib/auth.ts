import { apiClient, clearToken, storeToken } from "./api-client";

export { storeToken, clearToken };

export type ExchangeResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  tenant_id: number;
  user_id: number;
  role: string;
  is_super_admin: boolean;
  tenant_slug: string | null;
};

const USER_META_KEY = "tablescope.user_meta";

export function storeUserMeta(meta: {
  role: string;
  is_super_admin: boolean;
  tenant_id: number;
  user_id: number;
  tenant_slug?: string | null;
}): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(USER_META_KEY, JSON.stringify(meta));
  }
}

export function getUserMeta(): {
  role: string;
  is_super_admin: boolean;
  tenant_id: number;
  user_id: number;
  tenant_slug?: string | null;
} | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_META_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function exchangeWithSupabase(
  providerToken: string,
  tenantSlug?: string,
): Promise<ExchangeResponse> {
  return apiClient.post<ExchangeResponse>("/api/auth/exchange", {
    provider: "supabase",
    token: providerToken,
    tenant_slug: tenantSlug,
  });
}

export async function exchangeWithClerk(
  providerToken: string,
  tenantSlug?: string,
): Promise<ExchangeResponse> {
  return apiClient.post<ExchangeResponse>("/api/auth/exchange", {
    provider: "clerk",
    token: providerToken,
    tenant_slug: tenantSlug,
  });
}

export async function loginWithPassword(
  email: string,
  password: string,
  tenantSlug?: string,
): Promise<ExchangeResponse> {
  return apiClient.post<ExchangeResponse>("/api/auth/login", {
    email,
    password,
    tenant_slug: tenantSlug,
  });
}

export function signOut() {
  clearToken();
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
}
