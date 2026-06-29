import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const enrollPhone = vi.fn();
const challengePhone = vi.fn();
const verifyPhone = vi.fn();

vi.mock("@/lib/mfa", () => ({
  enrollPhone: (...a: unknown[]) => enrollPhone(...a),
  challengePhone: (...a: unknown[]) => challengePhone(...a),
  verifyPhone: (...a: unknown[]) => verifyPhone(...a),
}));

import { PhoneMfaForm } from "./phone-mfa-form";

describe("PhoneMfaForm", () => {
  beforeEach(() => {
    enrollPhone.mockReset();
    challengePhone.mockReset();
    verifyPhone.mockReset();
  });

  it("rejects a non-E.164 phone number without enrolling", async () => {
    render(<PhoneMfaForm mode="setup" onVerified={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText("+16615551212"), {
      target: { value: "6615551212" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));
    await waitFor(() =>
      expect(screen.getByText(/international format/i)).toBeTruthy(),
    );
    expect(enrollPhone).not.toHaveBeenCalled();
  });

  it("enrolls, challenges and verifies a valid E.164 number", async () => {
    enrollPhone.mockResolvedValue("factor-1");
    challengePhone.mockResolvedValue("challenge-1");
    verifyPhone.mockResolvedValue(undefined);
    const onVerified = vi.fn();
    render(<PhoneMfaForm mode="setup" onVerified={onVerified} />);

    fireEvent.change(screen.getByPlaceholderText("+16615551212"), {
      target: { value: "+16615551212" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));

    await waitFor(() => expect(challengePhone).toHaveBeenCalledWith("factor-1"));
    // Now on the code step.
    fireEvent.change(screen.getByPlaceholderText("123456"), {
      target: { value: "654321" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() =>
      expect(verifyPhone).toHaveBeenCalledWith(
        "factor-1",
        "challenge-1",
        "654321",
      ),
    );
    await waitFor(() => expect(onVerified).toHaveBeenCalled());
  });

  it("shows a friendly error on an invalid code and a resend cooldown", async () => {
    challengePhone.mockResolvedValue("challenge-9");
    verifyPhone.mockRejectedValue(new Error("Invalid code provided"));
    render(
      <PhoneMfaForm mode="challenge" factorId="factor-9" onVerified={vi.fn()} />,
    );

    // Auto-challenge fires on mount; wait for the code step + cooldown.
    await waitFor(() => expect(challengePhone).toHaveBeenCalledWith("factor-9"));
    await waitFor(() =>
      expect(screen.getByText(/resend code in/i)).toBeTruthy(),
    );

    fireEvent.change(screen.getByPlaceholderText("123456"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^verify$/i }));
    await waitFor(() =>
      expect(screen.getByText(/incorrect or expired/i)).toBeTruthy(),
    );
  });
});
