import { describe, expect, it } from "vitest";
import {
  IconSparkles,
  IconClipboardList,
  IconBuildingBank,
  IconBinaryTree,
} from "@tabler/icons-react";
import { projectNavGroups } from "@/components/tablescope/nav";

describe("Project Insights sidebar entry", () => {
  const groups = projectNavGroups("42");
  const project = groups.find((g) => g.heading === "Project");
  const insight = project?.items.find((i) => i.key === "project-insights");

  it("appears under Project labelled 'Project Insights'", () => {
    expect(insight).toBeTruthy();
    expect(insight?.label).toBe("Project Insights");
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

  it("moves resource links (Data Sources, Tables, Documents, Dashboards) to the top tab bar", () => {
    const all = project?.items ?? [];
    expect(all.some((i) => i.key === "project-data-sources")).toBe(false);
    expect(all.some((i) => i.key === "project-queries")).toBe(false);
    expect(all.some((i) => i.key === "project-documents")).toBe(false);
    expect(all.some((i) => i.key === "project-dashboards")).toBe(false);
  });

  it("orders the workflow sidebar as Project Home, Project Insights, Project Actions, Goals, Scopes, Knowledge Graph", () => {
    const all = project?.items ?? [];
    const keys = all.map((i) => i.key);
    expect(keys).toEqual([
      "overview",
      "project-insights",
      "project-actions",
      "project-business-context",
      "project-scopes",
      "project-create-knowledge-graph",
    ]);
  });

  it("keeps the Project Actions nav item after Project Insights", () => {
    const all = project?.items ?? [];
    const actions = all.find((i) => i.key === "project-actions");
    expect(actions).toBeTruthy();
    expect(actions?.label).toBe("Project Actions");
    expect(actions?.href).toBe("/projects/42/actions");
    expect(actions?.icon).toBe(IconClipboardList);
    const insightsIndex = all.findIndex((i) => i.key === "project-insights");
    expect(all.findIndex((i) => i.key === "project-actions")).toBe(
      insightsIndex + 1,
    );
  });

  it("keeps Goals and Scopes in the workflow sidebar", () => {
    const all = project?.items ?? [];
    const goal = all.find((i) => i.key === "project-business-context");
    expect(goal?.label).toBe("Goals");
    expect(goal?.icon).toBe(IconBuildingBank);
    const scopes = all.find((i) => i.key === "project-scopes");
    expect(scopes?.icon).toBe(IconBinaryTree);
  });
});
