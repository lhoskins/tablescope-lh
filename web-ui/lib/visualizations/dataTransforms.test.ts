import { describe, expect, it } from "vitest";
import { toNumber, preparePieData, toPercentStacked, isNumericColumn } from "./dataTransforms";

describe("toNumber", () => {
  it("parses numbers and numeric strings, stripping symbols", () => {
    expect(toNumber(42)).toBe(42);
    expect(toNumber("1,234")).toBe(1234);
    expect(toNumber("$5.50")).toBe(5.5);
    expect(toNumber("12%")).toBe(12);
  });

  it("returns null for non-numeric input", () => {
    expect(toNumber("abc")).toBeNull();
    expect(toNumber("")).toBeNull();
    expect(toNumber(null)).toBeNull();
    expect(toNumber(undefined)).toBeNull();
    expect(toNumber(NaN)).toBeNull();
  });
});

describe("preparePieData", () => {
  const rows = [
    { cat: "A", val: 50 },
    { cat: "B", val: 30 },
    { cat: "C", val: 10 },
    { cat: "D", val: 5 },
    { cat: "E", val: 3 },
  ];

  it("collapses categories beyond maxSlices into 'Other'", () => {
    const out = preparePieData(rows, { nameKey: "cat", valueKey: "val", maxSlices: 3 });
    expect(out).toHaveLength(3);
    expect(out[2]).toEqual({ cat: "Other", val: 18 });
  });

  it("leaves data unchanged when grouping is disabled", () => {
    const out = preparePieData(rows, { nameKey: "cat", valueKey: "val", maxSlices: 3, groupSmallSlices: false });
    expect(out).toHaveLength(5);
  });

  it("returns rows unchanged when count is within maxSlices", () => {
    const out = preparePieData(rows, { nameKey: "cat", valueKey: "val", maxSlices: 7 });
    expect(out).toHaveLength(5);
  });
});

describe("toPercentStacked", () => {
  it("normalizes each row's series to sum to 100", () => {
    const rows = [{ x: "Jan", a: 30, b: 10 }];
    const out = toPercentStacked(rows, "x", ["a", "b"]);
    expect(out[0].a).toBe(75);
    expect(out[0].b).toBe(25);
  });

  it("handles all-zero rows without dividing by zero", () => {
    const out = toPercentStacked([{ x: "Jan", a: 0, b: 0 }], "x", ["a", "b"]);
    expect(out[0].a).toBe(0);
    expect(out[0].b).toBe(0);
  });
});

describe("isNumericColumn", () => {
  it("detects numeric columns including numeric strings", () => {
    expect(isNumericColumn([{ v: 1 }, { v: "2" }, { v: "" }], "v")).toBe(true);
    expect(isNumericColumn([{ v: 1 }, { v: "x" }], "v")).toBe(false);
    expect(isNumericColumn([{ v: "" }, { v: null }], "v")).toBe(false);
  });
});
