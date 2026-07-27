import { describe, expect, it, vi } from "vitest";
import * as React from "react";
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

  // The reported failure: a mistyped code could not be corrected in place.
  // `autoFocus` was keyed on `digits.length`, so *every* deletion re-ran the
  // focus effect, which calls focus() and resets the caret to the end. Deleting
  // a wrong middle digit therefore jumped to the end and the replacement landed
  // there instead of where it was removed.
  //
  // These assert the effect's firing, not caret arithmetic: happy-dom does not
  // preserve `selectionStart` across a controlled-value update, so a
  // caret-position test here would encode the emulator's behaviour rather than
  // the component's.
  describe("correcting a mistake", () => {
    function Controlled({ initial }: { initial: string }) {
      const [value, setValue] = React.useState(initial);
      return <OtpInput value={value} onChange={setValue} autoFocus />;
    }

    it("autofocuses on mount", () => {
      render(<Controlled initial="" />);
      expect(document.activeElement).toBe(
        screen.getByLabelText(/verification code/i),
      );
    });

    it("does not re-grab focus when a digit is deleted", async () => {
      render(<Controlled initial="123456" />);
      const input = screen.getByLabelText(/verification code/i) as HTMLInputElement;
      input.blur();
      expect(document.activeElement).not.toBe(input);

      fireEvent.keyDown(input, { key: "Backspace" });
      await waitFor(() =>
        expect((screen.getByLabelText(/verification code/i) as HTMLInputElement).value)
          .toBe("12345"),
      );
      // Before the fix the length change re-ran the mount effect, which both
      // stole focus back and snapped the caret to the end.
      expect(document.activeElement).not.toBe(input);
    });

    it("does not re-grab focus when a digit is added", async () => {
      render(<Controlled initial="12" />);
      const input = screen.getByLabelText(/verification code/i) as HTMLInputElement;
      input.blur();
      fireEvent.keyDown(input, { key: "3" });
      await waitFor(() =>
        expect((screen.getByLabelText(/verification code/i) as HTMLInputElement).value)
          .toBe("123"),
      );
      expect(document.activeElement).not.toBe(input);
    });
  });
});
