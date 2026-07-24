import { describe, expect, it } from "vitest";
import { IconSparkles, IconLayoutDashboard, IconClipboardList } from "@tabler/icons-react";
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

  it("restores the Dashboards nav item after Documents", () => {
    const all = project?.items ?? [];
    const docsIndex = all.findIndex((i) => i.key === "project-documents");
    const dashboards = all.find((i) => i.key === "project-dashboards");
    expect(dashboards).toBeTruthy();
    expect(dashboards?.label).toBe("Dashboards");
    expect(dashboards?.href).toBe("/projects/42/dashboards");
    expect(dashboards?.icon).toBe(IconLayoutDashboard);
    expect(docsIndex).toBeGreaterThanOrEqual(0);
    expect(all.findIndex((i) => i.key === "project-dashboards")).toBe(
      docsIndex + 1,
    );
  });

  it("keeps the Project Actions nav item after Dashboards", () => {
    const all = project?.items ?? [];
    const dashboardsIndex = all.findIndex((i) => i.key === "project-dashboards");
    const actions = all.find((i) => i.key === "project-actions");
    expect(actions).toBeTruthy();
    expect(actions?.label).toBe("Project Actions");
    expect(actions?.href).toBe("/projects/42/actions");
    expect(actions?.icon).toBe(IconClipboardList);
    expect(dashboardsIndex).toBeGreaterThanOrEqual(0);
    expect(all.findIndex((i) => i.key === "project-actions")).toBe(
      dashboardsIndex + 1,
    );
  });
});
