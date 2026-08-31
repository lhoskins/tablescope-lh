import { describe, expect, it } from "vitest";
import { signedPercent } from "./signed-percent";

describe("signedPercent", () => {
  it("formats to exactly two decimals with a sign", () => {
    expect(signedPercent(0.2502)).toBe("+25.02%");
    expect(signedPercent(1.103)).toBe("+110.30%");
    expect(signedPercent(-0.05)).toBe("-5.00%");
    expect(signedPercent(0)).toBe("0.00%");
  });

  it("returns an em dash for non-finite input", () => {
    expect(signedPercent(NaN)).toBe("—");
  });
});
