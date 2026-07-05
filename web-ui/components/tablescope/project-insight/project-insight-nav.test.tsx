import { describe, expect, it } from "vitest";
import { IconSparkles } from "@tabler/icons-react";
import { projectNavGroups } from "@/components/tablescope/nav";

describe("Project Insight sidebar entry", () => {
  const groups = projectNavGroups("42");
  const intelligence = groups.find((g) => g.heading === "Intelligence");
  const insight = intelligence?.items.find(
    (i) => i.key === "project-insight",
  );

  it("appears under Intelligence labelled 'Project Insight'", () => {
    expect(insight).toBeTruthy();
    expect(insight?.label).toBe("Project Insight");
  });

  it("routes to the project insight page", () => {
    expect(insight?.href).toBe("/projects/42/insight");
  });

  it("keeps the same icon the old AI Assistant used (IconSparkles)", () => {
    expect(insight?.icon).toBe(IconSparkles);
  });

  it("no longer exposes the old 'AI Assistant' entry", () => {
    const all = groups.flatMap((g) => g.items);
    expect(all.some((i) => i.label === "AI Assistant")).toBe(false);
    expect(all.some((i) => i.key === "project-ai-assistant")).toBe(false);
  });
});
