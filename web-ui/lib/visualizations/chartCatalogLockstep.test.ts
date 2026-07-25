/**
 * Lockstep test: the chart-selection best-practices markdown (the single source
 * of truth for chart selection) and the ECharts renderer registry must never
 * drift. Every family declared in the markdown must be renderable; every
 * renderable family must be documented in the markdown.
 */
import { describe, expect, it } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { CHART_REGISTRY, CHART_ALIASES } from "./chartRegistry";

// Markdown families that render through a parent family's subtype/alias rather
// than a top-level registry key. Update alongside the markdown + registry.
const SUBTYPE_RESOLUTION: Record<string, string> = {
  waterfall: "bar", // bar subtype (running cumulative)
  bubble: "scatter", // scatter subtype (size dimension)
  histogram: "bar", // governed binning transform + bar rendering
  calendar_heatmap: "heatmap", // heatmap "calendar" subtype
  bump: "line", // line subtype (rank-over-time)
};

function loadCatalogMarkdown(): string {
  const candidates = [
    resolve(__dirname, "../../../platform-api/app/prompts/chart_selection_best_practices.md"),
    resolve(__dirname, "../../../ai-server/tablescope-ai-api/app/prompts/chart_selection_best_practices.md"),
  ];
  for (const p of candidates) {
    if (existsSync(p)) return readFileSync(p, "utf-8");
  }
  throw new Error(
    "chart_selection_best_practices.md not found — the lockstep test requires a full repo checkout",
  );
}

function markdownFamilies(text: string): string[] {
  const families: string[] = [];
  for (const m of text.matchAll(/^##\s+([a-z0-9_]+)\s*$/gm)) {
    families.push(m[1]);
  }
  return families;
}

describe("chart catalog markdown ⇄ renderer registry lockstep", () => {
  const md = loadCatalogMarkdown();
  const families = markdownFamilies(md);
  const registryKeys = new Set(Object.keys(CHART_REGISTRY));
  const aliasTargets = new Map(CHART_ALIASES.map((a) => [a.alias, a.type]));

  it("declares all 31 families", () => {
    expect(families).toHaveLength(31);
  });

  it("every markdown family is renderable (registry key, alias, or subtype parent)", () => {
    for (const family of families) {
      const parent = SUBTYPE_RESOLUTION[family];
      const renderable =
        registryKeys.has(family) ||
        aliasTargets.has(family) ||
        (parent !== undefined && registryKeys.has(parent));
      expect(renderable, `markdown family "${family}" has no renderer`).toBe(true);
    }
  });

  it("every registry family is documented in the markdown", () => {
    const documented = new Set(families);
    for (const key of registryKeys) {
      expect(documented.has(key), `registry family "${key}" missing from markdown`).toBe(true);
    }
  });

  it("every family section carries a rules block", () => {
    for (const family of families) {
      const section = md.split(new RegExp(`^## ${family}\\s*$`, "m"))[1] ?? "";
      const firstChunk = section.split(/^## /m)[0];
      expect(firstChunk.includes("```rules"), `family "${family}" has no rules block`).toBe(true);
    }
  });
});
