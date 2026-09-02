import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { InlineMarkdown, renderInlineMarkdown } from "./inline-markdown";

describe("renderInlineMarkdown", () => {
  it("renders **bold** spans as <strong> instead of literal asterisks", () => {
    const { container } = render(
      <p>
        <InlineMarkdown text="**WC-004** leads with **$506,713.68** in scrap cost." />
      </p>,
    );
    expect(container.textContent).toBe(
      "WC-004 leads with $506,713.68 in scrap cost.",
    );
    const strongEls = container.querySelectorAll("strong");
    expect(strongEls).toHaveLength(2);
    expect(strongEls[0].textContent).toBe("WC-004");
    expect(strongEls[1].textContent).toBe("$506,713.68");
  });

  it("leaves plain text with no markdown unchanged", () => {
    expect(renderInlineMarkdown("Network 44.43 hours")).toBe(
      "Network 44.43 hours",
    );
  });

  it("returns the raw text for an unpaired ** rather than dropping it", () => {
    const { container } = render(
      <p>
        <InlineMarkdown text="this is **not closed" />
      </p>,
    );
    expect(container.textContent).toBe("this is **not closed");
    expect(container.querySelector("strong")).toBeNull();
  });

  it("handles an empty string", () => {
    expect(renderInlineMarkdown("")).toBe("");
  });
});
