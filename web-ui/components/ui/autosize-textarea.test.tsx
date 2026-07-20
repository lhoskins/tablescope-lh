import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AutosizeTextarea } from "./autosize-textarea";

describe("AutosizeTextarea", () => {
  beforeEach(() => {
    // Provide predictable dimensions for jsdom's getComputedStyle.
    vi.spyOn(window, "getComputedStyle").mockReturnValue({
      lineHeight: "20px",
      fontSize: "13px",
    } as CSSStyleDeclaration);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a textarea with the configured row count", () => {
    render(<AutosizeTextarea value="" onChange={() => {}} minRows={2} maxRows={8} />);
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea).toBeTruthy();
    expect(textarea.getAttribute("rows")).toBe("2");
    expect(textarea.className).toContain("resize-none");
  });

  it("calls onChange when the user types", () => {
    const onChange = vi.fn();
    render(<AutosizeTextarea value="" onChange={onChange} />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "hello" } });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("calls onKeyDown for Enter and allows Shift+Enter to insert a newline", () => {
    const onKeyDown = vi.fn();
    const onChange = vi.fn();
    render(<AutosizeTextarea value="" onChange={onChange} onKeyDown={onKeyDown} />);
    const textarea = screen.getByRole("textbox");

    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    expect(onKeyDown).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(onKeyDown).toHaveBeenCalledTimes(2);
  });

  it("does not call onKeyDown while an IME composition is active", () => {
    const onKeyDown = vi.fn();
    const onChange = vi.fn();
    render(<AutosizeTextarea value="" onChange={onChange} onKeyDown={onKeyDown} />);
    const textarea = screen.getByRole("textbox");

    fireEvent.compositionStart(textarea);
    fireEvent.keyDown(textarea, { key: "Enter" });
    fireEvent.compositionEnd(textarea);
    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(onKeyDown).toHaveBeenCalledTimes(1);
  });
});
