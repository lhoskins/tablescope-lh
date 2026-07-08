import { describe, expect, it } from "vitest";
import { formatDateTime, formatLastUpdated } from "./format-datetime";

describe("formatDateTime", () => {
  it("renders a human-readable 12-hour date/time", () => {
    const out = formatDateTime(new Date(2026, 5, 21, 15, 45));
    expect(out).toBe("Jun 21, 2026 3:45 PM");
  });

  it("uses AM for morning times", () => {
    const out = formatDateTime(new Date(2026, 5, 21, 9, 5));
    expect(out).toBe("Jun 21, 2026 9:05 AM");
  });

  it("returns null for nullish or invalid input", () => {
    expect(formatDateTime(null)).toBeNull();
    expect(formatDateTime(undefined)).toBeNull();
    expect(formatDateTime("not-a-date")).toBeNull();
  });

  it("does not emit a raw ISO timestamp", () => {
    const out = formatDateTime(new Date(2026, 5, 21, 15, 45));
    expect(out).not.toMatch(/T\d{2}:\d{2}/);
  });
});

describe("formatLastUpdated", () => {
  it("prefixes the formatted value", () => {
    expect(formatLastUpdated(new Date(2026, 5, 21, 15, 45))).toBe(
      "Last updated: Jun 21, 2026 3:45 PM",
    );
  });

  it("returns null for nullish input", () => {
    expect(formatLastUpdated(null)).toBeNull();
  });
});
