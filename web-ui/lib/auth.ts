import { apiClient, clearToken, storeToken } from "./api-client";
import { getSupabaseClient } from "./supabase";

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

/**
 * Sign in with email + password via Supabase (the primary authenticator), then
 * exchange the resulting Supabase access token for a Tablescope session scoped
 * to the tenant. There is no local password store.
 */
export async function loginWithPassword(
  email: string,
  password: string,
  tenantSlug?: string,
): Promise<ExchangeResponse> {
  const supabase = getSupabaseClient();
  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });
  if (error) throw new Error(error.message);
  const accessToken = data.session?.access_token;
  if (!accessToken) throw new Error("Supabase did not return a session.");
  return exchangeWithSupabase(accessToken, tenantSlug);
}

/**
 * Email the user a Supabase password-reset link that lands on the tenant's
 * set-password page.
 */
export async function requestPasswordReset(
  email: string,
  tenantSlug: string,
): Promise<void> {
  const supabase = getSupabaseClient();
  const redirectTo =
    typeof window !== "undefined"
      ? `${window.location.origin}/${tenantSlug}/set-password`
      : undefined;
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo,
  });
  if (error) throw new Error(error.message);
}

/**
 * Set the password on the Supabase session established by an invite/recovery
 * link, then exchange for a Tablescope session.
 */
export async function setPasswordAndExchange(
  password: string,
  tenantSlug: string,
): Promise<ExchangeResponse> {
  const supabase = getSupabaseClient();
  const { error } = await supabase.auth.updateUser({ password });
  if (error) throw new Error(error.message);
  const { data } = await supabase.auth.getSession();
  const accessToken = data.session?.access_token;
  if (!accessToken) throw new Error("No active Supabase session.");
  return exchangeWithSupabase(accessToken, tenantSlug);
}

/** Whether a Supabase recovery/invite session is present (set-password flow). */
export async function hasSupabaseSession(): Promise<boolean> {
  const supabase = getSupabaseClient();
  const { data } = await supabase.auth.getSession();
  return Boolean(data.session);
}

export function signOut(options?: { redirectToRoot?: boolean }) {
  const meta = getUserMeta();
  const slug = meta?.tenant_slug;
  const redirectToRoot = options?.redirectToRoot ?? false;
  clearToken();
  try {
    void getSupabaseClient().auth.signOut();
  } catch {
    // Supabase may be unconfigured; ignore.
  }
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(USER_META_KEY);
    if (slug) {
      window.location.href = redirectToRoot ? `/${slug}` : `/${slug}/login`;
    } else {
      window.location.href = "/login";
    }
  }
}

// ── Idle timeout ─────────────────────────────────────────────────────
let idleTimer: ReturnType<typeof setTimeout> | null = null;

function resetIdleTimer() {
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    signOut({ redirectToRoot: true });
  }, IDLE_TIMEOUT_MS);
}

export function startIdleTimer() {
  if (typeof window === "undefined") return;
  const events = ["mousedown", "mousemove", "keydown", "scroll", "touchstart", "click"];
  events.forEach((evt) => window.addEventListener(evt, resetIdleTimer, { passive: true }));
  resetIdleTimer();
}

export function canManageProjectActions(
  role?: string,
  isSuperAdmin?: boolean,
): boolean {
  if (isSuperAdmin) return true;
  const allowed = [
    "member",
    "editor",
    "db_admin",
    "admin",
    "tenant_admin",
    "root_admin",
  ];
  return Boolean(role && allowed.includes(role.toLowerCase()));
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
