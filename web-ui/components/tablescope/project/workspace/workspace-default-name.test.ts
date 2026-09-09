import { describe, expect, it } from "vitest";
import { nextUntitledName } from "./workspace-default-name";

describe("nextUntitledName", () => {
  it("starts at Untitled-01 for an empty project", () => {
    expect(nextUntitledName([])).toBe("Untitled-01");
  });

  it("steps past the highest number in use, not the list length", () => {
    // The bug this replaces: deleting the middle of three and creating one
    // more produced a duplicate name.
    expect(
      nextUntitledName([{ name: "Untitled-01" }, { name: "Untitled-03" }]),
    ).toBe("Untitled-04");
  });

  it("ignores workspaces the user renamed", () => {
    expect(
      nextUntitledName([{ name: "Cost review" }, { name: "Vendor spend" }]),
    ).toBe("Untitled-01");
  });

  it("pads to two digits but does not truncate past nine", () => {
    expect(nextUntitledName([{ name: "Untitled-09" }])).toBe("Untitled-10");
    expect(nextUntitledName([{ name: "Untitled-99" }])).toBe("Untitled-100");
  });
});
