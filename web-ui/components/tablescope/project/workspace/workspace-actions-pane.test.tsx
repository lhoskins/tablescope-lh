import { describe, expect, it } from "vitest";
import { parseSuggestedActions } from "./workspace-actions-pane";

describe("parseSuggestedActions", () => {
  it("takes list items and strips their decoration", () => {
    const reply = [
      "Here are the actions I'd suggest:",
      "",
      "1. Automate access provisioning during onboarding",
      "2) Expire credentials on role change",
      "- Review the two stale-credential incidents",
      "* Chase the vendor invoice discrepancy",
      "• Share the Q2 metrics with IT ops",
      "",
      "Let me know if you'd like more detail.",
    ].join("\n");

    expect(parseSuggestedActions(reply)).toEqual([
      "Automate access provisioning during onboarding",
      "Expire credentials on role change",
      "Review the two stale-credential incidents",
      "Chase the vendor invoice discrepancy",
      "Share the Q2 metrics with IT ops",
    ]);
  });

  it("drops prose so a conversational reply doesn't become an action list", () => {
    // Replies that ignore the requested format must yield nothing rather than
    // turning whole paragraphs into checkboxes.
    expect(
      parseSuggestedActions(
        "I can't tell from these documents which spend is unexpected. Could you clarify?",
      ),
    ).toEqual([]);
  });

  it("removes bold and code markers left by markdown", () => {
    expect(parseSuggestedActions("- **Rotate** the `service_account` key")).toEqual([
      "Rotate the service_account key",
    ]);
  });

  it("handles an empty or missing message", () => {
    expect(parseSuggestedActions(null)).toEqual([]);
    expect(parseSuggestedActions("")).toEqual([]);
    expect(parseSuggestedActions("- \n-   ")).toEqual([]);
  });

  it("caps the list so one reply cannot flood the pane", () => {
    const many = Array.from({ length: 30 }, (_, i) => `- action ${i}`).join("\n");
    expect(parseSuggestedActions(many)).toHaveLength(10);
  });

  it("skips items too long to be an action", () => {
    const essay = `- ${"x".repeat(400)}`;
    expect(parseSuggestedActions(essay)).toEqual([]);
  });
});
