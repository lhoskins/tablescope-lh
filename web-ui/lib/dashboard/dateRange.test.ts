import { describe, expect, it } from "vitest";
import { resolveDatePreset, DATE_PRESETS } from "./dateRange";

const TODAY = new Date(2026, 4, 13); // 2026-05-13 (local)

describe("resolveDatePreset", () => {
  it("returns null for 'all' and 'custom'", () => {
    expect(resolveDatePreset("all", TODAY)).toBeNull();
    expect(resolveDatePreset("custom", TODAY)).toBeNull();
  });

  it("today is a single inclusive day", () => {
    expect(resolveDatePreset("today", TODAY)).toEqual({ start: "2026-05-13", end: "2026-05-13" });
  });

  it("yesterday", () => {
    expect(resolveDatePreset("yesterday", TODAY)).toEqual({ start: "2026-05-12", end: "2026-05-12" });
  });

  it("last_7_days spans 7 inclusive days ending today", () => {
    expect(resolveDatePreset("last_7_days", TODAY)).toEqual({ start: "2026-05-07", end: "2026-05-13" });
  });

  it("last_30_days spans 30 inclusive days", () => {
    expect(resolveDatePreset("last_30_days", TODAY)).toEqual({ start: "2026-04-14", end: "2026-05-13" });
  });

  it("this_month covers the full calendar month", () => {
    expect(resolveDatePreset("this_month", TODAY)).toEqual({ start: "2026-05-01", end: "2026-05-31" });
  });

  it("last_month covers the previous full month", () => {
    expect(resolveDatePreset("last_month", TODAY)).toEqual({ start: "2026-04-01", end: "2026-04-30" });
  });

  it("this_quarter for May resolves to Q2", () => {
    expect(resolveDatePreset("this_quarter", TODAY)).toEqual({ start: "2026-04-01", end: "2026-06-30" });
  });

  it("this_year covers Jan 1 to Dec 31", () => {
    expect(resolveDatePreset("this_year", TODAY)).toEqual({ start: "2026-01-01", end: "2026-12-31" });
  });

  it("exposes a preset list including custom", () => {
    expect(DATE_PRESETS.map((p) => p.id)).toContain("custom");
    expect(DATE_PRESETS.map((p) => p.id)).toContain("last_30_days");
  });
});
