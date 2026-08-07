import { describe, expect, it } from "vitest";
import { homeNavGroups, projectNavGroups } from "./nav";
import type { CurrentUser } from "@/lib/ui/types";

function makeUser(rawRole: string, isSuperAdmin = false): CurrentUser {
  return {
    id: 1,
    name: "Test",
    email: "test@example.com",
    role: rawRole,
    rawRole,
    tenantName: "Acme",
    initials: "T",
    isSuperAdmin,
    avatarUrl: null,
  };
}

function allItemKeys(groups: ReturnType<typeof homeNavGroups>): string[] {
  return groups.flatMap((g) => g.items.map((i) => i.key));
}

describe("homeNavGroups", () => {
  it("has no Tools group for admin users", () => {
    const groups = homeNavGroups(makeUser("admin"));
    expect(groups.find((g) => g.heading === "Tools")).toBeUndefined();
    const keys = allItemKeys(groups);
    expect(keys).not.toContain("data-source-builder");
    expect(keys).not.toContain("database-connectors");
    expect(keys).not.toContain("admin-data-source-assignments");
  });

  it("keeps the primary cross-project links", () => {
    const groups = homeNavGroups(makeUser("member"));
    const keys = allItemKeys(groups);
    expect(keys).toEqual([
      "home",
      "business-insight",
      "projects",
      "ai-assistant",
    ]);
  });
});

describe("projectNavGroups", () => {
  it("orders workflow items under the Project group", () => {
    const groups = projectNavGroups("7");
    const project = groups.find((g) => g.heading === "Project")?.items ?? [];
    const keys = project.map((i) => i.key);
    expect(keys).toEqual([
      "overview",
      "project-insights",
      "project-actions",
      "project-business-context",
      "project-scopes",
      "project-relationship-map",
    ]);
    expect(keys).not.toContain("project-data-sources");
    expect(keys).not.toContain("project-queries");
    expect(keys).not.toContain("project-documents");
    expect(keys).not.toContain("project-dashboards");
  });

  it("labels the overview route as Project Home", () => {
    const groups = projectNavGroups("7");
    const project = groups.find((g) => g.heading === "Project")?.items ?? [];
    const home = project.find((i) => i.key === "overview");
    expect(home?.label).toBe("Project Home");
    expect(home?.href).toBe("/projects/7");
  });

  it("replaces Intelligence with a Tools group containing only the builder", () => {
    const groups = projectNavGroups("7");
    expect(groups.find((g) => g.heading === "Intelligence")).toBeUndefined();
    const tools = groups.find((g) => g.heading === "Tools")?.items ?? [];
    expect(tools.map((i) => i.key)).toEqual(["project-data-source-builder"]);
    expect(tools.map((i) => i.href)).toEqual([
      "/projects/7/data-source-builder",
    ]);
    expect(tools.map((i) => i.label)).toEqual(["Data Source Builder"]);
  });

  it("does not include Intelligence items in project navigation", () => {
    const groups = projectNavGroups("7");
    const keys = allItemKeys(groups);
    expect(keys).not.toContain("project-knowledge-graph");
    expect(keys).not.toContain("project-metadata-catalog");
    expect(keys).not.toContain("project-reference-library");
    expect(keys).not.toContain("project-audit-log");
  });
});
