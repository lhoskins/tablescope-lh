import { apiClient, storeToken } from "./api-client";

/**
 * SMS MFA (primary MFA method) via Twilio Verify.
 *
 * The platform API owns the flow end-to-end: it sends the OTP through Twilio
 * Verify and, on a successful check, returns a fresh Tablescope token elevated
 * to aal2 (no Supabase phone-MFA factor / add-on involved). The verified phone
 * is persisted server-side (masked + hashed only).
 */

export type MfaStatus = {
  role: string;
  roleRequiresMfa: boolean;
  tenantRequiresMfa: boolean;
  aal: string | null;
  mfaSatisfied: boolean;
  hasVerifiedFactor: boolean;
  maskedPhone: string | null;
  preferredFactorType: string;
  requiredAction: string | null;
};

export type StartResponse = {
  maskedPhone: string;
  cooldownSeconds: number;
  status: string;
};

type VerifyResponse = {
  verified: boolean;
  access_token: string;
  token_type: string;
  expires_in: number;
  aal: string;
  maskedPhone: string | null;
};

export async function getMfaStatus(): Promise<MfaStatus> {
  return apiClient.get<MfaStatus>("/api/mfa/status");
}

/** Send an SMS verification code to the given E.164 number (enroll or challenge). */
export async function startPhone(phone: string): Promise<StartResponse> {
  return apiClient.post<StartResponse>("/api/mfa/phone/start", { phone });
}

/**
 * Verify the SMS code. On success the backend returns an aal2 token, which we
 * store immediately so subsequent requests carry the elevated assurance level.
 */
export async function verifyPhone(phone: string, code: string): Promise<void> {
  const result = await apiClient.post<VerifyResponse>("/api/mfa/phone/verify", {
    phone,
    code,
  });
  if (result.access_token) {
    storeToken(result.access_token);
  }
}

/** Remove the verified phone (disable MFA). Fails server-side if the role requires it. */
export async function removePhone(): Promise<void> {
  await apiClient.delete("/api/mfa/phone");
}
