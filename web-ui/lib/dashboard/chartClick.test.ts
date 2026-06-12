import { describe, expect, it } from "vitest";
import { normalizeCartesianClick, normalizePieClick } from "./chartClick";

describe("normalizeCartesianClick", () => {
  it("extracts the category from a bar/line click via activeLabel", () => {
    const ev = normalizeCartesianClick({ activeLabel: "March" }, "Month");
    expect(ev).toEqual({ sourceField: "Month", value: "March", label: "Month: March" });
  });

  it("humanizes underscored source fields in the label", () => {
    const ev = normalizeCartesianClick({ activeLabel: "Open" }, "ticket_status");
    expect(ev?.label).toBe("ticket status: Open");
  });

  it("supports numeric x values", () => {
    const ev = normalizeCartesianClick({ activeLabel: 2026 }, "Year");
    expect(ev).toEqual({ sourceField: "Year", value: 2026, label: "Year: 2026" });
  });

  it("returns null when nothing actionable was clicked", () => {
    expect(normalizeCartesianClick(null, "Month")).toBeNull();
    expect(normalizeCartesianClick({}, "Month")).toBeNull();
    expect(normalizeCartesianClick({ activeLabel: undefined }, "Month")).toBeNull();
  });
});

describe("normalizePieClick", () => {
  it("extracts the slice name from the name-key field", () => {
    const ev = normalizePieClick({ Status: "Open", value: 12 }, "Status", "Status");
    expect(ev).toEqual({ sourceField: "Status", value: "Open", label: "Status: Open" });
  });

  it("falls back to the 'name' field when name-key is absent", () => {
    const ev = normalizePieClick({ name: "Closed", value: 3 }, "Status", "Status");
    expect(ev?.value).toBe("Closed");
  });

  it("returns null for empty entries", () => {
    expect(normalizePieClick(null, "Status", "Status")).toBeNull();
    expect(normalizePieClick({}, "Status", "Status")).toBeNull();
  });
});
