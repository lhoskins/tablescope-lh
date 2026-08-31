import { describe, expect, it } from "vitest";
import { autoValueScale, formatFullPrecision, formatNumber } from "./format-number";

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
    expect(formatNumber(0.428, "percent", "thousands")).toBe("42.80%");
  });

  it("formats percent to exactly two decimals", () => {
    expect(formatNumber(0.2502, "percent")).toBe("25.02%");
    expect(formatNumber(1.103, "percent")).toBe("110.30%");
    expect(formatNumber(0.25, "percent")).toBe("25.00%");
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

describe("autoValueScale", () => {
  it("picks millions when the largest value is in the millions", () => {
    expect(autoValueScale([34_840_581.67, 6_662_211.37, 100])).toBe("millions");
  });

  it("picks thousands when the largest value is in the thousands but under a million", () => {
    expect(autoValueScale([5_000, 800_000, 42])).toBe("thousands");
  });

  it("picks no scale when every value is under a thousand", () => {
    expect(autoValueScale([1, 42, 999])).toBeUndefined();
  });

  it("ignores null/undefined/non-finite entries", () => {
    expect(autoValueScale([null, undefined, NaN, 2_000_000])).toBe("millions");
  });

  it("returns undefined for an empty or all-invalid list", () => {
    expect(autoValueScale([])).toBeUndefined();
    expect(autoValueScale([null, NaN])).toBeUndefined();
  });
});

describe("formatFullPrecision", () => {
  it("always shows two decimals with thousands separators", () => {
    expect(formatFullPrecision(34_840_581.67)).toBe("34,840,581.67");
    expect(formatFullPrecision(5_000_000)).toBe("5,000,000.00");
  });

  it("applies the currency symbol without abbreviating", () => {
    expect(formatFullPrecision(34_840_581.67, "currency")).toBe("$34,840,581.67");
    expect(formatFullPrecision(34_840_581.67, "currency", "€")).toBe("€34,840,581.67");
  });

  it("still caps percent at two decimals, no cents suffix", () => {
    expect(formatFullPrecision(0.2502, "percent")).toBe("25.02%");
  });

  it("returns an em dash for non-finite values", () => {
    expect(formatFullPrecision(NaN)).toBe("—");
  });
});
