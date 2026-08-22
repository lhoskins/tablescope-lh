import { describe, expect, it } from "vitest";
import { formatNumber } from "./format-number";

describe("formatNumber", () => {
  it("auto-picks K/M breakpoints for currency when scale is unset", () => {
    expect(formatNumber(950, "currency")).toBe("$950");
    expect(formatNumber(12_500, "currency")).toBe("$13K");
    expect(formatNumber(4_200_000, "currency")).toBe("$4.2M");
  });

  it("forces the requested unit regardless of magnitude when scale is set", () => {
    expect(formatNumber(4_200_000, "currency", "thousands")).toBe("$4,200K");
    expect(formatNumber(950, "currency", "millions")).toBe("$0M");
    expect(formatNumber(12_500, "number", "hundreds")).toBe("125H");
  });

  it('scale "auto" behaves the same as omitting it', () => {
    expect(formatNumber(4_200_000, "currency", "auto")).toBe(formatNumber(4_200_000, "currency"));
  });

  it("never rescales a percent value", () => {
    expect(formatNumber(0.428, "percent", "thousands")).toBe("42.8%");
  });

  it("defaults to $ when no currencySymbol is given (backward compatible)", () => {
    expect(formatNumber(950, "currency")).toBe("$950");
    expect(formatNumber(4_200_000, "currency", "thousands")).toBe("$4,200K");
  });

  it("uses the requested currency symbol wherever currency formatting applies", () => {
    expect(formatNumber(950, "currency", undefined, "€")).toBe("€950");
    expect(formatNumber(12_500, "currency", undefined, "€")).toBe("€13K");
    expect(formatNumber(4_200_000, "currency", undefined, "€")).toBe("€4.2M");
    expect(formatNumber(4_200_000, "currency", "thousands", "€")).toBe("€4,200K");
  });

  it("does not apply the currency symbol to non-currency formats", () => {
    expect(formatNumber(4_200_000, "number", undefined, "€")).toBe("4,200,000");
    expect(formatNumber(4_200_000, "compact", undefined, "€")).toBe("4.2M");
  });
});
