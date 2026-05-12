import { apiClient, clearToken, storeToken } from "./api-client";

export { storeToken, clearToken };

export type ExchangeResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  tenant_id: number;
  user_id: number;
  role: string;
};

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

export function signOut() {
  clearToken();
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
}
