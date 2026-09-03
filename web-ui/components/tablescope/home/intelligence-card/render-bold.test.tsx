import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { renderBold } from "./render-bold";

describe("renderBold", () => {
  it("renders **bold** spans as <strong>, matching literal text otherwise", () => {
    const { container } = render(
      <p>{renderBold("Open actions rose from **16.0** in **2026-02** to a peak.")}</p>,
    );
    expect(container.textContent).toBe(
      "Open actions rose from 16.0 in 2026-02 to a peak.",
    );
    const strongEls = container.querySelectorAll("strong");
    expect(strongEls).toHaveLength(2);
    expect(strongEls[0].textContent).toBe("16.0");
    expect(strongEls[1].textContent).toBe("2026-02");
  });

  it("strips a stray unpaired ** instead of leaving it visible", () => {
    const { container } = render(<p>{renderBold("this is **not closed")}</p>);
    expect(container.textContent).toBe("this is not closed");
    expect(container.querySelector("strong")).toBeNull();
  });

  it("leaves plain text with no markdown unchanged", () => {
    const { container } = render(<p>{renderBold("Network 44.43 hours")}</p>);
    expect(container.textContent).toBe("Network 44.43 hours");
  });
});
