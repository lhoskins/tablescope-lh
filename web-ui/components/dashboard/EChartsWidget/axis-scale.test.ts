import { describe, expect, it } from "vitest";
import { axisScaleLabel, formatAxisNumber } from "./axis-scale";

describe("axis scale", () => {
  it("divides ticks by the selected display unit and labels the axis", () => {
    const options = { yAxisScale: "thousands" as const, yAxisFormat: "number" as const };
    expect(formatAxisNumber(37_100_000, options)).toBe("37,100");
    expect(axisScaleLabel(options)).toBe("Thousands");
  });

  it("does not change values when actual values are selected", () => {
    expect(formatAxisNumber(15_000, { yAxisScale: "none" })).toBe("15,000");
    expect(axisScaleLabel({ yAxisScale: "none" })).toBeUndefined();
  });

  it("still applies the per-chart valueScale unit when no display unit is set", () => {
    expect(formatAxisNumber(2_500_000, { valueScale: "millions" })).toBe("2.5M");
    expect(formatAxisNumber(2_500, { yAxisScale: "none", valueScale: "thousands" })).toBe("2.5K");
  });

  it("uses the dashboard's selected currency symbol in both display-unit paths", () => {
    expect(
      formatAxisNumber(2_500_000, { yAxisFormat: "currency", valueScale: "millions", currencySymbol: "€" }),
    ).toBe("€2.5M");
    // yAxisScale divides the value first (37,100,000 / 1,000 = 37,100), then
    // "currency" format's own K/M auto-compacting still applies on top.
    expect(
      formatAxisNumber(37_100_000, { yAxisScale: "thousands", yAxisFormat: "currency", currencySymbol: "€" }),
    ).toBe("€37K");
  });
});
