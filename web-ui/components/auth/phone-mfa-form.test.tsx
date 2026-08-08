import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

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

  it("defaults to United States (+1) and rejects an invalid number", async () => {
    render(<PhoneMfaForm mode="setup" onVerified={vi.fn()} />);

    const countrySelect = screen.getByLabelText(/country/i) as HTMLSelectElement;
    expect(countrySelect.value).toBe("US");

    const phoneInput = screen.getByLabelText(/mobile phone number/i);
    fireEvent.change(phoneInput, { target: { value: "123" } });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));

    await waitFor(() =>
      expect(screen.getByText(/enter a valid phone number/i)).toBeTruthy(),
    );
    expect(startPhone).not.toHaveBeenCalled();
  });

  it("normalizes a valid U.S. national number to E.164 and sends it", async () => {
    startPhone.mockResolvedValue({
      maskedPhone: "+1******1212",
      cooldownSeconds: 60,
      status: "pending",
    });
    verifyPhone.mockResolvedValue(undefined);
    const onVerified = vi.fn();
    render(<PhoneMfaForm mode="setup" onVerified={onVerified} />);

    const phoneInput = screen.getByLabelText(/mobile phone number/i);
    fireEvent.change(phoneInput, { target: { value: "6615551212" } });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));

    await waitFor(() =>
      expect(startPhone).toHaveBeenCalledWith("+16615551212"),
    );

    const codeInput = await waitFor(() =>
      screen.getByLabelText(/verification code/i),
    );
    fireEvent.change(codeInput, { target: { value: "654321" } });
    fireEvent.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() =>
      expect(verifyPhone).toHaveBeenCalledWith("+16615551212", "654321"),
    );
    await waitFor(() => expect(onVerified).toHaveBeenCalled());
  });

  it("normalizes a UK number when that country is selected", async () => {
    startPhone.mockResolvedValue({
      maskedPhone: "+44******7890",
      cooldownSeconds: 60,
      status: "pending",
    });
    render(<PhoneMfaForm mode="setup" onVerified={vi.fn()} />);

    const countrySelect = screen.getByLabelText(/country/i);
    fireEvent.change(countrySelect, { target: { value: "GB" } });

    const phoneInput = screen.getByLabelText(/mobile phone number/i);
    fireEvent.change(phoneInput, { target: { value: "07123456789" } });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));

    await waitFor(() =>
      expect(startPhone).toHaveBeenCalledWith("+447123456789"),
    );
  });

  it("shows a friendly error on an invalid code and a resend cooldown", async () => {
    startPhone.mockResolvedValue({
      maskedPhone: "+1******1212",
      cooldownSeconds: 60,
      status: "pending",
    });
    verifyPhone.mockRejectedValue(new Error("That code is incorrect or expired."));
    render(<PhoneMfaForm mode="challenge" onVerified={vi.fn()} />);

    const phoneInput = screen.getByLabelText(/mobile phone number/i);
    fireEvent.change(phoneInput, { target: { value: "6615551212" } });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));

    await waitFor(() =>
      expect(screen.getByText(/resend code in/i)).toBeTruthy(),
    );

    const codeInput = screen.getByLabelText(/verification code/i);
    fireEvent.change(codeInput, { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() =>
      expect(screen.getByText(/incorrect or expired/i)).toBeTruthy(),
    );
  });

  it("does not submit a five-digit code", async () => {
    startPhone.mockResolvedValue({
      maskedPhone: "+1******1212",
      cooldownSeconds: 60,
      status: "pending",
    });
    render(<PhoneMfaForm mode="setup" onVerified={vi.fn()} />);

    const phoneInput = screen.getByLabelText(/mobile phone number/i);
    fireEvent.change(phoneInput, { target: { value: "6615551212" } });
    fireEvent.click(screen.getByRole("button", { name: /send code/i }));

    await waitFor(() =>
      expect(screen.getByLabelText(/verification code/i)).toBeTruthy(),
    );

    const codeInput = screen.getByLabelText(/verification code/i);
    fireEvent.change(codeInput, { target: { value: "12345" } });
    fireEvent.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() =>
      expect(screen.getByText(/6-digit code/i)).toBeTruthy(),
    );
    expect(verifyPhone).not.toHaveBeenCalled();
  });
});
