import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useAccordion } from "./use-accordion";

describe("useAccordion", () => {
  it("starts with nothing open by default", () => {
    const { result } = renderHook(() => useAccordion());
    expect(result.current.activePanel).toBeNull();
    expect(result.current.isOpen("a")).toBe(false);
  });

  it("opens a panel when toggled", () => {
    const { result } = renderHook(() => useAccordion());
    act(() => result.current.toggle("a"));
    expect(result.current.isOpen("a")).toBe(true);
  });

  it("collapses the active panel when it is toggled again", () => {
    const { result } = renderHook(() => useAccordion("a"));
    act(() => result.current.toggle("a"));
    expect(result.current.activePanel).toBeNull();
    expect(result.current.isOpen("a")).toBe(false);
  });

  it("expanding a panel collapses every other panel", () => {
    const { result } = renderHook(() => useAccordion());
    act(() => result.current.toggle("a"));
    act(() => result.current.toggle("b"));
    expect(result.current.isOpen("a")).toBe(false);
    expect(result.current.isOpen("b")).toBe(true);
    expect(result.current.activePanel).toBe("b");
  });
});
