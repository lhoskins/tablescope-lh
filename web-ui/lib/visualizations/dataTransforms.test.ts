import { describe, expect, it } from "vitest";
import {
  toNumber,
  preparePieData,
  toPercentStacked,
  isNumericColumn,
  prepareTreemapData,
  prepareFunnelData,
  prepareRadarData,
  prepareSankeyData,
} from "./dataTransforms";

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

describe("prepareTreemapData", () => {
  it("builds name/size leaves and drops non-positive values", () => {
    const out = prepareTreemapData(
      [{ svc: "EC2", cost: "1,000" }, { svc: "S3", cost: 0 }, { svc: "RDS", cost: 250 }],
      { nameKey: "svc", valueKey: "cost" }
    );
    expect(out).toEqual([{ name: "EC2", size: 1000 }, { name: "RDS", size: 250 }]);
  });
});

describe("prepareFunnelData", () => {
  it("sorts stages descending and drops zero values", () => {
    const out = prepareFunnelData(
      [{ stage: "Open", n: 10 }, { stage: "Won", n: 0 }, { stage: "Qualified", n: 40 }],
      { nameKey: "stage", valueKey: "n" }
    );
    expect(out).toEqual([{ name: "Qualified", value: 40 }, { name: "Open", value: 10 }]);
  });
});

describe("prepareRadarData", () => {
  it("pivots long rows into one record per subject with a column per series", () => {
    const rows = [
      { metric: "Speed", vendor: "A", score: 80 },
      { metric: "Speed", vendor: "B", score: 60 },
      { metric: "Cost", vendor: "A", score: 70 },
    ];
    const { data, series } = prepareRadarData(rows, { subjectKey: "metric", valueKey: "score", seriesKey: "vendor" });
    expect(series).toEqual(["A", "B"]);
    expect(data).toContainEqual({ metric: "Speed", A: 80, B: 60 });
    expect(data.find((d) => d.metric === "Cost")).toMatchObject({ A: 70 });
  });

  it("uses a single series named by valueKey when no seriesKey is given", () => {
    const { series } = prepareRadarData([{ m: "X", v: 1 }], { subjectKey: "m", valueKey: "v" });
    expect(series).toEqual(["v"]);
  });
});

describe("prepareSankeyData", () => {
  it("builds shared node indices and sums duplicate links", () => {
    const rows = [
      { src: "Web", dst: "Auth", val: 5 },
      { src: "Web", dst: "Auth", val: 3 },
      { src: "Auth", dst: "DB", val: 4 },
    ];
    const { nodes, links } = prepareSankeyData(rows, { sourceKey: "src", targetKey: "dst", valueKey: "val" });
    expect(nodes.map((n) => n.name)).toEqual(["Web", "Auth", "DB"]);
    expect(links).toContainEqual({ source: 0, target: 1, value: 8 });
    expect(links).toContainEqual({ source: 1, target: 2, value: 4 });
  });

  it("skips rows missing source, target, or a positive value", () => {
    const { links } = prepareSankeyData(
      [{ s: "", t: "B", v: 1 }, { s: "A", t: "", v: 1 }, { s: "A", t: "B", v: 0 }],
      { sourceKey: "s", targetKey: "t", valueKey: "v" }
    );
    expect(links).toHaveLength(0);
  });
});
