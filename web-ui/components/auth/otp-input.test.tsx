import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OtpInput } from "./otp-input";

describe("OtpInput", () => {
  it("renders six cells and a hidden input", () => {
    const { container } = render(<OtpInput value="" onChange={vi.fn()} />);
    expect(screen.getByLabelText(/verification code/i)).toBeTruthy();
    expect(container.querySelectorAll("button").length).toBe(6);
  });

  it("types six digits into the cells", async () => {
    const onChange = vi.fn();
    render(<OtpInput value="" onChange={onChange} />);
    const input = screen.getByLabelText(/verification code/i);
    fireEvent.change(input, { target: { value: "123456" } });
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith("123456"));
  });

  it("pastes a six-digit code", async () => {
    const onChange = vi.fn();
    render(<OtpInput value="" onChange={onChange} />);
    const input = screen.getByLabelText(/verification code/i);
    fireEvent.paste(input, {
      clipboardData: { getData: () => "ABC-456-789" },
    });
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith("456789"));
  });

  it("strips non-digits and caps at six", async () => {
    const onChange = vi.fn();
    render(<OtpInput value="" onChange={onChange} />);
    const input = screen.getByLabelText(/verification code/i);
    fireEvent.change(input, { target: { value: "12a345b6c7" } });
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith("123456"));
  });
});
