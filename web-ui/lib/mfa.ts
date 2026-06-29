import { apiClient } from "./api-client";
import { exchangeWithSupabase, storeToken, storeUserMeta } from "./auth";
import { getSupabaseClient } from "./supabase";

/**
 * Twilio SMS MFA (primary MFA method).
 *
 * Supabase owns factor enrollment / challenge / verification and the aal2
 * session upgrade; Twilio delivers the SMS (via the backend Send-SMS hook).
 * After a successful verify the Supabase session is aal2, so we re-exchange it
 * for a fresh Tablescope token that carries the new assurance level.
 */

export type MfaStatus = {
  role: string;
  roleRequiresMfa: boolean;
  aal: string | null;
  mfaSatisfied: boolean;
  preferredFactorType: string;
  requiredAction: string | null;
};

export type PhoneFactor = {
  id: string;
  status: string;
  phone?: string | null;
  friendlyName?: string | null;
};

export async function getMfaStatus(): Promise<MfaStatus> {
  return apiClient.get<MfaStatus>("/api/mfa/status");
}

export async function listPhoneFactors(): Promise<PhoneFactor[]> {
  const supabase = getSupabaseClient();
  const { data, error } = await supabase.auth.mfa.listFactors();
  if (error) throw new Error(error.message);
  const phone = (data?.phone ?? []) as Array<{
    id: string;
    status: string;
    phone?: string | null;
    friendly_name?: string | null;
  }>;
  return phone.map((f) => ({
    id: f.id,
    status: f.status,
    phone: f.phone ?? null,
    friendlyName: f.friendly_name ?? null,
  }));
}

export async function getCurrentAal(): Promise<string | null> {
  const supabase = getSupabaseClient();
  const { data, error } =
    await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
  if (error) throw new Error(error.message);
  return data?.currentLevel ?? null;
}

/** Returns a verified phone factor, or null if none is verified yet. */
export async function getVerifiedPhoneFactor(): Promise<PhoneFactor | null> {
  const factors = await listPhoneFactors();
  return factors.find((f) => f.status === "verified") ?? null;
}

/** Enroll a phone factor. Returns the factorId to challenge against. */
export async function enrollPhone(phone: string): Promise<string> {
  const supabase = getSupabaseClient();
  const { data, error } = await supabase.auth.mfa.enroll({
    factorType: "phone",
    phone,
  });
  if (error) throw new Error(error.message);
  return data.id;
}

/** Send an SMS challenge for a factor. Returns the challengeId. */
export async function challengePhone(factorId: string): Promise<string> {
  const supabase = getSupabaseClient();
  const { data, error } = await supabase.auth.mfa.challenge({ factorId });
  if (error) throw new Error(error.message);
  return data.id;
}

/** Verify the SMS code, upgrading the session to aal2. */
export async function verifyPhone(
  factorId: string,
  challengeId: string,
  code: string,
): Promise<void> {
  const supabase = getSupabaseClient();
  const { error } = await supabase.auth.mfa.verify({
    factorId,
    challengeId,
    code,
  });
  if (error) throw new Error(error.message);
}

export async function unenrollPhone(factorId: string): Promise<void> {
  const supabase = getSupabaseClient();
  const { error } = await supabase.auth.mfa.unenroll({ factorId });
  if (error) throw new Error(error.message);
}

/**
 * After verify() upgrades the Supabase session to aal2, re-exchange the new
 * access token so the Tablescope session reflects aal2 to the backend.
 */
export async function refreshTablescopeSession(
  tenantSlug?: string | null,
): Promise<void> {
  const supabase = getSupabaseClient();
  const { data, error } = await supabase.auth.getSession();
  if (error) throw new Error(error.message);
  const accessToken = data.session?.access_token;
  if (!accessToken) throw new Error("No Supabase session to refresh.");
  const result = await exchangeWithSupabase(
    accessToken,
    tenantSlug || undefined,
  );
  storeToken(result.access_token);
  storeUserMeta({
    role: result.role,
    is_super_admin: result.is_super_admin,
    tenant_id: result.tenant_id,
    user_id: result.user_id,
    tenant_slug: result.tenant_slug,
  });
}
