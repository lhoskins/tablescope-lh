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

describe("homeNavGroups", () => {
  it("places Data Source Assignments after Database Connectors for admin users", () => {
    const groups = homeNavGroups(makeUser("admin"));
    const tools = groups.find((g) => g.heading === "Tools")?.items ?? [];
    const keys = tools.map((i) => i.key);
    expect(keys).toEqual([
      "data-source-builder",
      "database-connectors",
      "admin-data-source-assignments",
    ]);
  });

  it("does not include Data Source Assignments for regular members", () => {
    const groups = homeNavGroups(makeUser("member"));
    const tools = groups.find((g) => g.heading === "Tools")?.items ?? [];
    const keys = tools.map((i) => i.key);
    expect(keys).not.toContain("admin-data-source-assignments");
  });

  it("includes Data Source Assignments for super admins", () => {
    const groups = homeNavGroups(makeUser("member", true));
    const tools = groups.find((g) => g.heading === "Tools")?.items ?? [];
    const keys = tools.map((i) => i.key);
    expect(keys).toContain("admin-data-source-assignments");
  });
});

describe("projectNavGroups", () => {
  it("orders workflow items and removes resource links from the sidebar", () => {
    const groups = projectNavGroups("7");
    const project = groups.find((g) => g.heading === "Project")?.items ?? [];
    const keys = project.map((i) => i.key);
    expect(keys).toEqual([
      "overview",
      "project-insights",
      "project-actions",
      "project-business-context",
      "project-scopes",
      "project-create-knowledge-graph",
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

  it("keeps the Intelligence section unchanged", () => {
    const groups = projectNavGroups("7");
    const intelligence = groups.find((g) => g.heading === "Intelligence")?.items ?? [];
    expect(intelligence.map((i) => i.key)).toEqual([
      "project-knowledge-graph",
      "project-metadata-catalog",
      "project-reference-library",
      "project-audit-log",
    ]);
  });
});
