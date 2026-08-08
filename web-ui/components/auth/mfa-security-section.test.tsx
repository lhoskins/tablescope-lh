import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const getMfaStatus = vi.fn();
const removePhone = vi.fn();

vi.mock("@/lib/mfa", () => ({
  getMfaStatus: (...a: unknown[]) => getMfaStatus(...a),
  removePhone: (...a: unknown[]) => removePhone(...a),
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
    removePhone.mockReset();
  });

  it("shows Enabled with the verified phone when a factor exists", async () => {
    getMfaStatus.mockResolvedValue({
      role: "admin",
      roleRequiresMfa: true,
      tenantRequiresMfa: false,
      aal: "aal2",
      mfaSatisfied: true,
      hasVerifiedFactor: true,
      maskedPhone: "+1******1212",
      preferredFactorType: "phone",
      requiredAction: null,
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
      tenantRequiresMfa: false,
      aal: "aal1",
      mfaSatisfied: false,
      hasVerifiedFactor: false,
      maskedPhone: null,
      preferredFactorType: "phone",
      requiredAction: "setup",
    });
    render(<MfaSecuritySection />);
    await waitFor(() =>
      expect(screen.getByText(/sms verification is required/i)).toBeTruthy(),
    );
    expect(
      screen.getByRole("button", { name: /add phone number/i }),
    ).toBeTruthy();
  });
});
