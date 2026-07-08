import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const startPhone = vi.fn();
const verifyPhone = vi.fn();

vi.mock("@/lib/mfa", () => ({
  startPhone: (...a: unknown[]) => startPhone(...a),
  verifyPhone: (...a: unknown[]) => verifyPhone(...a),
}));

import { PhoneMfaForm } from "./phone-mfa-form";

describe("PhoneMfaForm", () => {
  beforeEach(() => {
    startPhone.mockReset();
    verifyPhone.mockReset();
  });

  it("rejects a non-E.164 phone number without sending a code", async () => {
    render(<PhoneMfaForm mode="setup" onVerified={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText("+16615551212"), {
      target: { value: "6615551212" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));
    await waitFor(() =>
      expect(screen.getByText(/international format/i)).toBeTruthy(),
    );
    expect(startPhone).not.toHaveBeenCalled();
  });

  it("sends a code and verifies a valid E.164 number", async () => {
    startPhone.mockResolvedValue({
      maskedPhone: "+1******1212",
      cooldownSeconds: 60,
      status: "pending",
    });
    verifyPhone.mockResolvedValue(undefined);
    const onVerified = vi.fn();
    render(<PhoneMfaForm mode="setup" onVerified={onVerified} />);

    fireEvent.change(screen.getByPlaceholderText("+16615551212"), {
      target: { value: "+16615551212" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));

    await waitFor(() =>
      expect(startPhone).toHaveBeenCalledWith("+16615551212"),
    );
    // Now on the code step (wait for the async re-render to the code input).
    const codeInput = await screen.findByPlaceholderText("123456");
    fireEvent.change(codeInput, {
      target: { value: "654321" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() =>
      expect(verifyPhone).toHaveBeenCalledWith("+16615551212", "654321"),
    );
    await waitFor(() => expect(onVerified).toHaveBeenCalled());
  });

  it("shows a friendly error on an invalid code and a resend cooldown", async () => {
    startPhone.mockResolvedValue({
      maskedPhone: "+1******1212",
      cooldownSeconds: 60,
      status: "pending",
    });
    verifyPhone.mockRejectedValue(new Error("That code is incorrect or expired."));
    render(<PhoneMfaForm mode="challenge" onVerified={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText("+16615551212"), {
      target: { value: "+16615551212" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));

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
