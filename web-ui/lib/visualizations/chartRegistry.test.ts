import { describe, expect, it } from "vitest";
import {
  CHART_REGISTRY,
  CHART_ALIASES,
  getChartDefinition,
  resolveRendererType,
  getDefaultOptions,
  withDefaults,
} from "./chartRegistry";

describe("chartRegistry", () => {
  it("includes every supported widget type", () => {
    for (const type of [
      "kpi", "table", "line", "area", "bar", "combo", "pie",
      "scatter", "effect_scatter", "radar", "radial_bar", "treemap",
      "funnel", "sankey", "gauge",
    ]) {
      expect(CHART_REGISTRY[type as keyof typeof CHART_REGISTRY]).toBeDefined();
    }
  });

  it("each chart type declares required fields and an icon", () => {
    for (const def of Object.values(CHART_REGISTRY)) {
      expect(Array.isArray(def.requiredFields)).toBe(true);
      expect(def.icon.length).toBeGreaterThan(0);
      expect(def.label.length).toBeGreaterThan(0);
    }
  });

  it("getChartDefinition returns undefined for unknown types", () => {
    expect(getChartDefinition("not_a_chart")).toBeUndefined();
    expect(getChartDefinition("line")?.family).toBe("line");
  });

  it("resolveRendererType falls back to table for unknown types", () => {
    expect(resolveRendererType("not_a_chart")).toBe("table");
    expect(resolveRendererType("treemap")).toBe("treemap");
    expect(resolveRendererType("bar")).toBe("bar");
  });

  it("getDefaultOptions builds defaults from the registry", () => {
    const lineDefaults = getDefaultOptions("line");
    expect(lineDefaults.lineStyle).toBe("solid");
    expect(lineDefaults.showLegend).toBe(true);
    expect(lineDefaults.curveType).toBe("monotone");
  });

  it("withDefaults overlays saved options over defaults", () => {
    const merged = withDefaults("line", { lineStyle: "dashed", showLegend: false });
    expect(merged.lineStyle).toBe("dashed");
    expect(merged.showLegend).toBe(false);
    // untouched default preserved
    expect(merged.curveType).toBe("monotone");
  });

  it("pie defaults group small slices with a max of 7", () => {
    const pie = getDefaultOptions("pie");
    expect(pie.groupSmallSlices).toBe(true);
    expect(pie.maxSlices).toBe(7);
  });

  it("aliases map to a valid renderer type", () => {
    for (const alias of CHART_ALIASES) {
      expect(CHART_REGISTRY[alias.type]).toBeDefined();
    }
    const donut = CHART_ALIASES.find((a) => a.alias === "donut");
    expect(donut?.type).toBe("pie");
    expect(donut?.options?.innerRadius).toBe(55);
    const bubble = CHART_ALIASES.find((a) => a.alias === "bubble");
    expect(bubble?.type).toBe("scatter");
    expect(bubble?.options?.bubble).toBe(true);
  });

  it("new chart families expose option definitions", () => {
    for (const type of ["scatter", "radar", "radial_bar", "treemap", "funnel", "sankey"]) {
      expect(getChartDefinition(type)?.options.length).toBeGreaterThan(0);
    }
  });

  it("variant presets carry option overrides applied on selection", () => {
    const barVariants = getChartDefinition("bar")?.variants ?? [];
    const waterfall = barVariants.find((v) => v.value === "waterfall");
    expect(waterfall?.defaultOptions?.cumulative).toBe(true);
    const posNeg = barVariants.find((v) => v.value === "positive_negative");
    expect(posNeg?.defaultOptions?.colorBySign).toBe(true);

    const lineVariants = getChartDefinition("line")?.variants ?? [];
    expect(lineVariants.find((v) => v.value === "dashed_line")?.defaultOptions?.lineStyle).toBe("dashed");
    expect(lineVariants.find((v) => v.value === "biaxial_line")?.defaultOptions?.dualAxis).toBe(true);

    const scatterVariants = getChartDefinition("scatter")?.variants ?? [];
    expect(scatterVariants.find((v) => v.value === "best_fit")?.defaultOptions?.showTrendLine).toBe(true);

    const pieVariants = getChartDefinition("pie")?.variants ?? [];
    expect(pieVariants.find((v) => v.value === "two_level")).toBeDefined();
    expect(pieVariants.find((v) => v.value === "gauge")?.defaultOptions?.endAngle).toBe(0);

    expect((getChartDefinition("treemap")?.variants ?? []).some((v) => v.value === "nested")).toBe(true);
  });
});
