import { describe, expect, it } from "vitest";
import { buildAiAssistantHref } from "./ai-assistant";

describe("buildAiAssistantHref", () => {
  it("returns /ai with no arguments", () => {
    expect(buildAiAssistantHref({})).toBe("/ai");
  });

  it("builds a full conversation/project/turn/origin URL", () => {
    expect(
      buildAiAssistantHref({
        projectId: 5,
        conversationId: 48,
        turnId: 203,
        origin: "project-overview",
      }),
    ).toBe("/ai?conversation=48&projectId=5&turn=203&from=project-overview");
  });

  it("builds a project-filter/origin URL", () => {
    expect(
      buildAiAssistantHref({
        projectId: "5",
        origin: "project-overview",
      }),
    ).toBe("/ai?projectId=5&from=project-overview");
  });

  it("omits undefined values", () => {
    expect(
      buildAiAssistantHref({
        conversationId: 10,
        query: undefined,
      }),
    ).toBe("/ai?conversation=10");
  });

  it("encodes query text safely", () => {
    expect(
      buildAiAssistantHref({
        query: "hello world & more=",
      }),
    ).toBe("/ai?q=hello+world+%26+more%3D");
  });

  it("ignores unknown origin values at the type boundary", () => {
    expect(
      buildAiAssistantHref({
        projectId: 3,
        origin: "project-overview",
      }),
    ).toBe("/ai?projectId=3&from=project-overview");
    // Casting to test runtime behavior for a disallowed origin value.
    expect(
      buildAiAssistantHref({
        projectId: 3,
        origin: "malicious" as "project-overview",
      }),
    ).toBe("/ai?projectId=3");
  });
});
