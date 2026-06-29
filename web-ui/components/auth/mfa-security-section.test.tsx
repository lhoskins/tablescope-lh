import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const getMfaStatus = vi.fn();
const getVerifiedPhoneFactor = vi.fn();
const unenrollPhone = vi.fn();
const refreshTablescopeSession = vi.fn();

vi.mock("@/lib/mfa", () => ({
  getMfaStatus: (...a: unknown[]) => getMfaStatus(...a),
  getVerifiedPhoneFactor: (...a: unknown[]) => getVerifiedPhoneFactor(...a),
  unenrollPhone: (...a: unknown[]) => unenrollPhone(...a),
  refreshTablescopeSession: (...a: unknown[]) => refreshTablescopeSession(...a),
}));

vi.mock("@/lib/auth", () => ({
  getUserMeta: () => ({ tenant_slug: "boeing" }),
}));

vi.mock("@/components/auth/phone-mfa-form", () => ({
  PhoneMfaForm: () => <div data-testid="phone-form" />,
}));

import { MfaSecuritySection } from "./mfa-security-section";

describe("MfaSecuritySection", () => {
  beforeEach(() => {
    getMfaStatus.mockReset();
    getVerifiedPhoneFactor.mockReset();
    unenrollPhone.mockReset();
  });

  it("shows Enabled with the verified phone when a factor exists", async () => {
    getMfaStatus.mockResolvedValue({
      role: "admin",
      roleRequiresMfa: true,
      aal: "aal2",
      mfaSatisfied: true,
      preferredFactorType: "phone",
      requiredAction: null,
    });
    getVerifiedPhoneFactor.mockResolvedValue({
      id: "f1",
      status: "verified",
      phone: "+1******1212",
    });
    render(<MfaSecuritySection />);
    await waitFor(() => expect(screen.getByText("Enabled")).toBeTruthy());
    expect(screen.getByText(/\+1\*+1212/)).toBeTruthy();
    // Required role cannot remove the factor.
    const remove = screen.getByRole("button", { name: /remove/i });
    expect(remove.hasAttribute("disabled")).toBe(true);
  });

  it("warns and offers to add a phone for a required role without a factor", async () => {
    getMfaStatus.mockResolvedValue({
      role: "admin",
      roleRequiresMfa: true,
      aal: "aal1",
      mfaSatisfied: false,
      preferredFactorType: "phone",
      requiredAction: "setup_or_challenge",
    });
    getVerifiedPhoneFactor.mockResolvedValue(null);
    render(<MfaSecuritySection />);
    await waitFor(() =>
      expect(screen.getByText(/role requires sms verification/i)).toBeTruthy(),
    );
    expect(
      screen.getByRole("button", { name: /add phone number/i }),
    ).toBeTruthy();
  });
});
