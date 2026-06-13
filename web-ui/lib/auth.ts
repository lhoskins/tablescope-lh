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
const IDLE_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes

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

/**
 * Read a Supabase access token from the URL hash fragment left by a magic-link
 * redirect (e.g. `#access_token=...&refresh_token=...`). Clears the fragment so
 * the credential isn't left in the address bar / history. Returns null if none.
 */
export function readSupabaseTokenFromHash(): string | null {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash;
  if (!hash || !hash.includes("access_token")) return null;
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const accessToken = params.get("access_token");
  if (accessToken) {
    const url = window.location.pathname + window.location.search;
    window.history.replaceState(null, "", url);
  }
  return accessToken;
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
  const meta = getUserMeta();
  const slug = meta?.tenant_slug;
  clearToken();
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(USER_META_KEY);
    window.location.href = slug ? `/${slug}/login` : "/login";
  }
}

// ── Idle timeout ─────────────────────────────────────────────────────
let idleTimer: ReturnType<typeof setTimeout> | null = null;

function resetIdleTimer() {
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    signOut();
  }, IDLE_TIMEOUT_MS);
}

export function startIdleTimer() {
  if (typeof window === "undefined") return;
  const events = ["mousedown", "mousemove", "keydown", "scroll", "touchstart", "click"];
  events.forEach((evt) => window.addEventListener(evt, resetIdleTimer, { passive: true }));
  resetIdleTimer();
}

export function stopIdleTimer() {
  if (typeof window === "undefined") return;
  if (idleTimer) {
    clearTimeout(idleTimer);
    idleTimer = null;
  }
  const events = ["mousedown", "mousemove", "keydown", "scroll", "touchstart", "click"];
  events.forEach((evt) => window.removeEventListener(evt, resetIdleTimer));
}
