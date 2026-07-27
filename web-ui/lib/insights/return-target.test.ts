import { describe, expect, it } from "vitest";
import { insightAnchorId, insightReturnHref } from "./return-target";

describe("returning to the originating insight", () => {
  it("links back to the card, not the top of the feed", () => {
    expect(insightReturnHref("/business-insight", "abc-123")).toBe(
      "/business-insight#insight-abc-123",
    );
  });

  it("escapes ids so an odd character cannot break the hash", () => {
    expect(insightReturnHref("/business-insight", "a b/c#d")).toBe(
      "/business-insight#insight-a%20b%2Fc%23d",
    );
  });

  it("falls back to the plain feed when there is no id to return to", () => {
    expect(insightReturnHref("/business-insight", "")).toBe("/business-insight");
  });

  it("uses the same anchor id the feed renders", () => {
    // The href and the DOM id must agree or the scroll silently does nothing.
    const id = "abc-123";
    expect(insightReturnHref("/business-insight", id)).toBe(
      `/business-insight#${insightAnchorId(id)}`,
    );
  });
});
